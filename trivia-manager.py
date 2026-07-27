from multiprocessing import Lock
from multiprocessing.managers import BaseManager
import atexit
import pickle
import uuid
import answer_normalize



trivia_data_server = BaseManager(('localhost', 5555), b'trivia')
trivia_set_lock=Lock() # TODO: Get a seperate lock for every trivia set. It's excessive to lock the entire list.
users_lock=Lock()

users={}
trivia_sets=[]


# trivia json specification:
# [
#  {'type':'multiple select',
#   'question':'what are the factors of 6?',
#   'possible responses': ['12', '2', '4', '3'],
#   'correct answers':['2','3']
#  },
#  {'type':'short answer',
#   'question': 'Who was the first president of the US?',
#   'correct answers':['George Washington', 'President George Washington']
#  },
#  {'type':'multiple choice',
#  'question': 'What is the role of RAM in a computer?',
#  'possible responses': ['long term storage of information', 'processing math', 'producing audio effects', 'fast temporary storage'],
#  'correct answers':['fast temporary storage']
#  }
# ]

class TriviaSet():
    def __init__(self, trivia_specification, creator=None):
        self.trivia=trivia_specification
        self.creator=creator
        self.num_questions=len(trivia_specification)
        ## Analytics gives the creator of the trivia information about the responses to 
        ## the questions. 'correct' increments for every correct answer, 'incorrect'
        ## increments for every incorrect answer. 'responses' holds the individual 
        ## responses, along with the UUID of the user who gave it.
        self.analytics=[{'correct':0,'incorrect':0, 'responses':[]}*self.num_questions]


    def verify_answer(self, index, answer_to_test):
        if(self.trivia[index]['type']=='multiple select'): # all of the answers to test & correct answers must match
            return set(map(answer_normalize.normalize(answer_to_test)))== \
                       set(map(answer_normalize.normalize(self.trivia[index]['correct answers'])))
        else: #the answer to test only has to match a single correct answer.
            return any(map(lambda x: answer_normalize.same(answer_to_test[0], x), self.trivia[index]['correct answers']))


    def get_question(self, index):
        ret = self.trivia[index].copy()
        ret['correct_answers']=None    # prevent the client from scraping the password.
        return ret




class User():
    def __init__(self, username, password, UUID):
        self.username=username
        self.password=password
        self.UUID=UUID 
        





def get_trivia(idx_of_trivia_set, question_idx): # TODO: make this secure. Include a passcode with every trivia set that only authorized users have.
    global trivia_sets
    with trivia_set_lock:
        if(question_idx>=trivia_sets[idx_of_trivia_set]):
            return False
        return trivia_sets[idx_of_trivia_set].get_question(question_idx)

def get_analytics(idx_of_trivia_set): # TODO: This should only be available to the creator of the trivia.
    global trivia_sets
    with trivia_set_lock:
        return trivia_sets[idx_of_trivia_set].analytics

def get_user(UUID):
    global users
    with user_lock:
        result = users[UUID].copy()
        result.password=None ## DO NOT SEND PASSWORDS TO ANYBODY WHO ASKS
        return result

def verify_answer(UUID, idx_of_trivia_set, question_idx, answer):
    global trivia_sets
    with trivia_set_lock:
        
        result = trivia_sets[idx_of_trivia_set].verify_answer(question_idx, answer)
        if(result is True):
            trivia_sets[idx_of_trivia_set].analytics[question_idx]['correct']+=1
        else:
            trivia_sets[idx_of_trivia_set].analytics[question_idx]['incorrect']+=1
        trivia_sets[idx_of_trivia_set].analytics['responses']+=[(UUID, answer)]
        return result


def new_trivia_set(trivia_json):
    global trivia_sets
    with trivia_set_lock:
        trivia_sets+=[TriviaSet(trivia_json)]
        return len(trivia_sets)-1

def register_user(username, password):
    global users
    with users_lock:
        if any(map(lambda x: x.username==username, users.values())):
            return "username already taken"
        new_uuid = uuid.uuid4().hex
        users[new_uuid]=User(username, password, new_uuid)
        return new_uuid



@atexit.register
def goodbye(): #TODO: save trivia sets and users.
    pass


trivia_data_server.register('get_trivia', get_trivia)
trivia_data_server.register('verify_answer', verify_answer)
trivia_data_server.register('new_trivia_set', new_trivia_set)
trivia_data_server.register('register_user', register_user)
trivia_data_server.register('get_user', get_user)
trivia_data_server.register('get_analytics', get_analytics)

server= trivia_data_server.get_server()
server.serve_forever()







