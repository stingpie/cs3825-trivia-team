from flask import Flask, session, request, jsonify, Response
from multiprocessing.managers import BaseManager
import secrets

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
def get_trivia():
    if('UUID' in session and 'idx_of_trivia_set' in session and 'question_idx' in session):
        result = trivia_data_server.get_trivia(session['idx_of_trivia_set'], session['question_idx'])
        if(result):
            return jsonify(result)
        else:
            return "Error in getting the next question.", 500
    if('UUID' not in session):
        return "User not logged in.", 401 # unauthorized
    if('idx_of_trivia_set' not in session):
        return "No active trivia set selected.", 400
    if('question_idx' not in session):
        return "No question index found", 400
        
@app.route("/api/trivia/verify", methods=["GET"])
def verify_answer(): # should recieve {'answer':['something seomthing something']} returns {'correct':true|false}
    answer = request.get_json()['question']
    if('UUID' in session and 'idx_of_trivia_set' in session and 'question_idx' in session):
        response={}
        response['correct']=trivia_data_server.verify_answer(session['UUID'], session['idx_of_trivia_set'], session['question_idx'])
        return jsonify(response)
    if('UUID' not in session):
        return "User not logged in.", 401 # unauthorized
    if('idx_of_trivia_set' not in session):
        return "No active trivia set selected.", 400
    if('question_idx' not in session):
        return "No question index found", 400

@app.route("/api/trivia/next", methods=["GET"])
def next_question():
    if('UUID' in session and 'idx_of_trivia_set' in session and 'question_idx' in session):
        session['question_idx']+=1
        result = get_trivia()
        if(isinstance(result, tuple) and result[1]<300):
            return result
        elif(isinstance(result, tuple) and result[1]>=300):
            pass # TODO: this is probably the end of the trivia quiz.
        else:
            return result
            
@app.route("/api/trivia", methods=["POST"])
def create_trivia():
    trivia_json = request.get_json()
    return str(trivia_data_server.new_trivia_set(trivia_json))

@app.route("/api/users", methods=['POST'])
def create_user(): # should recieve {'username':"asldjad", "password":"alsdjoa"} returns 201 on success
    user_info = request.get_json()
    username= user_info['username']
    password = user_info['password']
    result = str(trivia_data_server.register_user(username, password))
    if result=="username already taken":
        return Response(str(result), 409)
    session['UUID']=result
    session['idx_of_trivia_set']=0
    session['question_idx']=0
    return Response('new user created!', 201)


@app.route("/api/trivia/analytics", methods=["GET"])
def get_analytics():
    idx_of_trivia_set=request.get_json()['idx_of_trivia_set']
    return trivia_data_server.get_analytics(idx_of_trivia_set)

@app.route("/api/users", methods=['POST'])
def get_user():
    UUID=request.get_json()['UUID']
    return trivia_data_server.get_user(UUID)




