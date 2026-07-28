from flask import Flask, session, request, jsonify, Response
from multiprocessing.managers import BaseManager
import secrets

# --- Security & Reliability integration (Jordan) ---------------------------
# security.py and reliability.py must sit next to this file (or be installed
# on the Python path). See those files for full docstrings.
from security import (
    require_role,
    require_login,
    require_valid_signature,
    issue_login_session,
)
from reliability import record_heartbeat, save_reconnect_state, load_reconnect_state
# -----------------------------------------------------------------------------

app= Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)


trivia_data_server=BaseManager(('localhost', 5555), b'trivia')
trivia_data_server.register('get_trivia')
trivia_data_server.register('verify_answer')
trivia_data_server.register('new_trivia_set')
trivia_data_server.register('register_user')
trivia_data_server.register('get_user')
trivia_data_server.register('get_analytics')
trivia_data_server.connect()


@app.route("/")
def hello_world():
    return "<p> hello, world</p>"

@app.route("/api/trivia", methods=["GET"])
@require_login  # was a manual 'UUID' in session check -- now handled by the decorator
def get_trivia():
    if('idx_of_trivia_set' in session and 'question_idx' in session):
        result = trivia_data_server.get_trivia(session['idx_of_trivia_set'], session['question_idx'])
        if(result):
            # Snapshot progress on every fetch so a dropped client can resume here.
            save_reconnect_state(session['UUID'], session['idx_of_trivia_set'], session['question_idx'])
            return jsonify(result)
        else:
            return "Error in getting the next question.", 500
    if('idx_of_trivia_set' not in session):
        return "No active trivia set selected.", 400
    if('question_idx' not in session):
        return "No question index found", 400

@app.route("/api/trivia/verify", methods=["GET"])
@require_login
@require_valid_signature  # J2: rejects tampered SUBMIT_ANSWER-style payloads
def verify_answer(): # should recieve {'answer':['something seomthing something']} returns {'correct':true|false}
    answer = request.get_json()['question']
    if('idx_of_trivia_set' in session and 'question_idx' in session):
        response={}
        response['correct']=trivia_data_server.verify_answer(session['UUID'], session['idx_of_trivia_set'], session['question_idx'])
        return jsonify(response)
    if('idx_of_trivia_set' not in session):
        return "No active trivia set selected.", 400
    if('question_idx' not in session):
        return "No question index found", 400

@app.route("/api/trivia/next", methods=["GET"])
@require_login
def next_question():
    if('idx_of_trivia_set' in session and 'question_idx' in session):
        session['question_idx']+=1
        result = get_trivia()
        if(isinstance(result, tuple) and result[1]<300):
            return result
        elif(isinstance(result, tuple) and result[1]>=300):
            pass # TODO: this is probably the end of the trivia quiz.
        else:
            return result

@app.route("/api/trivia", methods=["POST"])
@require_role("teacher")       # J3: RBAC -- only teachers can create trivia sets
@require_valid_signature       # J2: reject tampered quiz-creation payloads
def create_trivia():
    trivia_json = request.get_json()
    return str(trivia_data_server.new_trivia_set(trivia_json))

@app.route("/api/users", methods=['POST'])
def create_user(): # should recieve {'username':"asldjad", "password":"alsdjoa", "role":"student"|"teacher"} returns 201 on success
    user_info = request.get_json()
    username = user_info['username']
    password = user_info['password']
    role = user_info.get('role', 'student')  # default to the lower-privilege role
    # NOTE: register_user (trivia-manager.py) is responsible for calling
    # security.hash_password() before storing this -- never store plaintext.
    result = str(trivia_data_server.register_user(username, password, role))
    if result=="username already taken":
        return Response(str(result), 409)
    issue_login_session(result, role)  # sets session['UUID'], session['role'], etc.
    return Response('new user created!', 201)

@app.route("/api/login", methods=["POST"])
def login():  # should receive {'username':..., 'password':...}
    creds = request.get_json()
    username = creds['username']
    password = creds['password']
    # get_user_by_credentials should live in trivia-manager.py and internally
    # call security.verify_password() against the stored bcrypt hash.
    result = trivia_data_server.get_user_by_credentials(username, password)
    if not result:
        return jsonify({"error": "invalid username or password"}), 401
    issue_login_session(result['UUID'], result['role'])
    return jsonify({"role": result['role']}), 200


@app.route("/api/trivia/analytics", methods=["GET"])
@require_role("teacher")  # J3: students should never see the answer-key-adjacent analytics
def get_analytics():
    idx_of_trivia_set=request.get_json()['idx_of_trivia_set']
    return trivia_data_server.get_analytics(idx_of_trivia_set)

# NOTE: this used to share the exact same route + method as create_user()
# above ("/api/users", POST), which silently shadows one of the two view
# functions in Flask. Split onto its own path/method so both are reachable.
@app.route("/api/users/<uuid>", methods=['GET'])
@require_login
def get_user(uuid):
    return trivia_data_server.get_user(uuid)


@app.route("/api/heartbeat", methods=["POST"])
@require_login
def heartbeat():  # client sends {'type':'PING','timestamp':...} every 5s
    return jsonify(record_heartbeat(session['UUID']))


@app.route("/api/reconnect", methods=["GET"])
@require_login
def reconnect():
    """
    Lets a client that dropped Wi-Fi ask "where was I?" using its existing
    session token, instead of restarting the quiz from question 0.
    """
    state = load_reconnect_state(session['UUID'])
    if state is None:
        return jsonify({"error": "no saved progress for this session"}), 404
    session['idx_of_trivia_set'] = state['idx_of_trivia_set']
    session['question_idx'] = state['question_idx']
    return jsonify(state)
