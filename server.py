from flask import Flask, session, request, jsonify, Response, render_template
from multiprocessing.managers import BaseManager
import secrets
import time
import os

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
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-stable-secret-key-cs3825')


trivia_data_server=BaseManager(('localhost', 5555), b'trivia')
trivia_data_server.register('get_trivia')
trivia_data_server.register('verify_answer')
trivia_data_server.register('new_trivia_set')
trivia_data_server.register('register_user')
trivia_data_server.register('get_user')
trivia_data_server.register('get_user_by_credentials')  # was missing -- login() needs this
trivia_data_server.register('get_analytics')
# Darren: game-room lobby RPCs (shared across hosts via trivia-manager)
trivia_data_server.register('create_room')
trivia_data_server.register('join_room')
trivia_data_server.register('get_room')
trivia_data_server.register('start_room')
trivia_data_server.register('leave_room')


def _connect_with_retry(manager, attempts=10, delay_seconds=1.0):
    """
    trivia-manager.py has to be up and listening before this process can
    connect. Rather than dying on the first ConnectionRefusedError if it
    hasn't finished starting yet, retry briefly and give a clear error.
    """
    last_error = None
    for _ in range(attempts):
        try:
            manager.connect()
            return
        except ConnectionRefusedError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(
        "Could not connect to the trivia-manager backend at localhost:5555. "
        "Make sure trivia-manager.py is running before starting server.py."
    ) from last_error


_connect_with_retry(trivia_data_server)


def _unwrap(value):
    """
    Every call through trivia_data_server (e.g. trivia_data_server.get_user(...))
    comes back as an AutoProxy object, not the plain value the underlying
    function returned -- proxies can't be subscripted ([...]), iterated, or
    JSON-serialized. _getvalue() pulls the real (picklable) value across
    once, right where we receive it, so the rest of the route can treat it
    like an ordinary dict/list/bool.
    """
    if hasattr(value, "_getvalue"):
        return value._getvalue()
    return value


@app.route('/')
def index():
    return render_template('index.html')

@app.route("/api/trivia", methods=["GET"])
@require_login  # was a manual 'UUID' in session check -- now handled by the decorator
def get_trivia():
    if('idx_of_trivia_set' in session and 'question_idx' in session):
        result = _unwrap(trivia_data_server.get_trivia(session['idx_of_trivia_set'], session['question_idx']))
        if(result):
            # Snapshot progress on every fetch so a dropped client can resume here.
            save_reconnect_state(
                session['UUID'],
                session['idx_of_trivia_set'],
                session['question_idx'],
                room_code=session.get('room_code'),
            )
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
    answer = request.get_json()['answer']
    if('idx_of_trivia_set' in session and 'question_idx' in session):
        response={}
        response['correct']=_unwrap(trivia_data_server.verify_answer(session['UUID'], session['idx_of_trivia_set'], session['question_idx'], answer))
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
            # get_trivia() returned its "no such question" error, which means
            # we've stepped past the last question -- this is the end of the
            # quiz, not a server error. Leave the session pointed at the last
            # valid question and tell the client the quiz is done.
            session['question_idx']-=1
            return jsonify({"done": True, "message": "You've reached the end of the quiz."}), 200
        else:
            return result
    if('idx_of_trivia_set' not in session):
        return "No active trivia set selected.", 400
    if('question_idx' not in session):
        return "No question index found", 400

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
    raw_result = trivia_data_server.register_user(username, password, role)
    result = str(_unwrap(raw_result))
    if result=="username already taken":
        return Response(result, status=409)
    issue_login_session(result, role)  # sets session['UUID'], session['role'], etc.
    return Response('new user created!', status=201)

@app.route("/api/login", methods=["POST"])
def login():  # should receive {'username':..., 'password':...}
    creds = request.get_json()
    username = creds['username']
    password = creds['password']
    # get_user_by_credentials should live in trivia-manager.py and internally
    # call security.verify_password() against the stored bcrypt hash.
    result = _unwrap(trivia_data_server.get_user_by_credentials(username, password))
    if not result:
        return jsonify({"error": "invalid username or password"}), 401
    issue_login_session(result['UUID'], result['role'])
    return jsonify({"role": result['role']}), 200


@app.route("/api/trivia/analytics", methods=["GET"])
@require_role("teacher")  # J3: students should never see the answer-key-adjacent analytics
def get_analytics():
    idx_of_trivia_set=request.get_json()['idx_of_trivia_set']
    return jsonify(_unwrap(trivia_data_server.get_analytics(idx_of_trivia_set)))

# NOTE: this used to share the exact same route + method as create_user()
# above ("/api/users", POST), which silently shadows one of the two view
# functions in Flask. Split onto its own path/method so both are reachable.
@app.route("/api/users/<uuid>", methods=['GET'])
@require_login
def get_user(uuid):
    return jsonify(_unwrap(trivia_data_server.get_user(uuid)))


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
    if state.get('room_code'):
        session['room_code'] = state['room_code']
    return jsonify(state)


# --- Game room lobbies (Darren) ---------------------------------------------

def _lobby_error(result):
    """Map lobby error strings from trivia-manager to HTTP responses."""
    mapping = {
        "trivia set not found": 404,
        "host not found": 404,
        "player not found": 404,
        "room not found": 404,
        "room has ended": 409,
        "only the host can start the room": 403,
    }
    status = mapping.get(result, 400)
    return jsonify({"error": result}), status


def _apply_room_to_session(room_view):
    """Bind the Flask session to a lobby so GET /api/trivia uses that quiz."""
    session['room_code'] = room_view['room_code']
    session['idx_of_trivia_set'] = room_view['idx_of_trivia_set']
    session['question_idx'] = room_view.get('question_idx', 0)
    save_reconnect_state(
        session['UUID'],
        session['idx_of_trivia_set'],
        session['question_idx'],
        room_code=session['room_code'],
    )


@app.route("/api/rooms", methods=["POST"])
@require_role("teacher")
def create_room():
    """
    CREATE_ROOM -- teacher opens a lobby for a trivia set.
    Body: {"idx_of_trivia_set": 0, "pacing_mode": "self"|"host"}
    """
    body = request.get_json(silent=True) or {}
    if "idx_of_trivia_set" not in body:
        return jsonify({"error": "idx_of_trivia_set is required"}), 400
    result = _unwrap(trivia_data_server.create_room(
        session['UUID'],
        body['idx_of_trivia_set'],
        body.get('pacing_mode', 'self'),
    ))
    if isinstance(result, str):
        return _lobby_error(result)
    _apply_room_to_session(result)
    return jsonify(result), 201


@app.route("/api/rooms/join", methods=["POST"])
@require_login
def join_room():
    """
    JOIN_ROOM -- student enters a 4-digit PIN from the host display.
    Body: {"room_code": "4821"}
    """
    body = request.get_json(silent=True) or {}
    room_code = body.get('room_code')
    if not room_code:
        return jsonify({"error": "room_code is required"}), 400
    result = _unwrap(trivia_data_server.join_room(room_code, session['UUID']))
    if isinstance(result, str):
        return _lobby_error(result)
    _apply_room_to_session(result)
    return jsonify(result), 200


@app.route("/api/rooms/<room_code>", methods=["GET"])
@require_login
def get_room(room_code):
    """GET_ROOM -- poll lobby roster / status (waiting vs active)."""
    result = _unwrap(trivia_data_server.get_room(room_code))
    if result is None:
        return jsonify({"error": "room not found"}), 404
    return jsonify(result), 200


@app.route("/api/rooms/<room_code>/start", methods=["POST"])
@require_role("teacher")
def start_room(room_code):
    """START_ROOM -- host flips the lobby from waiting to active."""
    result = _unwrap(trivia_data_server.start_room(room_code, session['UUID']))
    if isinstance(result, str):
        return _lobby_error(result)
    _apply_room_to_session(result)
    return jsonify(result), 200


@app.route("/api/rooms/leave", methods=["POST"])
@require_login
def leave_room():
    """LEAVE_ROOM -- drop out of the current session lobby."""
    room_code = session.get('room_code')
    if not room_code:
        body = request.get_json(silent=True) or {}
        room_code = body.get('room_code')
    if not room_code:
        return jsonify({"error": "not in a room"}), 400
    result = _unwrap(trivia_data_server.leave_room(room_code, session['UUID']))
    if isinstance(result, str):
        return _lobby_error(result)
    session.pop('room_code', None)
    return jsonify(result), 200
