from flask import Flask, session, request, jsonify
from multiprocessing.managers import BaseManager

app= Flask(__name__)

trivia_data_server=BaseManager(('localhost', 5555))
trivia_data_server.register('get_trivia')
trivia_data_server.register('verify_answer')
trivia_data_server.register('new_trivia_set')
trivia_data_server.register('register_user')

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
def verify_answer(): # should recieve {'answer':'something seomthing something'} returns {'correct':true|false}
    answer = request.get_json()['question']
    if('UUID' in session and 'idx_of_trivia_set' in session and 'question_idx' in session):
        response={}
        response['correct']=trivia_data_server.verify_answer(session['idx_of_trivia_set'], session['question_idx'])
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
            


@app.route("/api/users", methods=['POST'])
def create_user(): # should recieve {'username':"asldjad", "password":"alsdjoa"} returns 201 on success
    user_info = request.get_json()
    username= user_info['username']
    password = user_info['password']
    result = trivia_data_server.register_user(username, password)
    if isinstance(result, str):
        return result, 409
    session['UUID']=result
    session['idx_of_trivia_set']=0
    session['question_idx']=0
    return 'new user created!', 201






