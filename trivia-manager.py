from multiprocessing import Lock
from multiprocessing.managers import BaseManager
import atexit
import pickle
import time
import uuid
import answer_normalize

# --- Security integration (Jordan) ------------------------------------------
# security.py must sit next to this file (or be installed on the Python path).
from security import hash_password, verify_password
# -----------------------------------------------------------------------------

# --- Lobby integration (Darren) ---------------------------------------------
from lobby import generate_room_code, make_room, public_room_view
# -----------------------------------------------------------------------------



trivia_data_server = BaseManager(('localhost', 5555), b'trivia')
trivia_set_lock=Lock() # TODO: Get a seperate lock for every trivia set. It's excessive to lock the entire list.
users_lock=Lock()
rooms_lock=Lock()

users={}
trivia_sets=[]
rooms={}  # room_code (4-digit PIN) -> room dict (see lobby.make_room)


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
        self.analytics=[{'correct':0,'incorrect':0, 'responses':[]} for _ in range(self.num_questions)]


    def verify_answer(self, index, answer_to_test):
        if(self.trivia[index]['type']=='multiple select'): # all of the answers to test & correct answers must match
            given = set(map(answer_normalize.normalize, answer_to_test))
            correct = set(map(answer_normalize.normalize, self.trivia[index]['correct answers']))
            return given == correct
        else: #the answer to test only has to match a single correct answer.
            return any(map(lambda x: answer_normalize.same(answer_to_test[0], x), self.trivia[index]['correct answers']))


    def get_question(self, index):
        ret = self.trivia[index].copy()
        ret.pop('correct answers', None)  # prevent the client from scraping the answer key
        return ret




class User():
    def __init__(self, username, password_hash, UUID, role="student"):
        self.username=username
        self.password=password_hash  # J1: this is now a bcrypt hash, never plaintext
        self.UUID=UUID
        self.role=role  # J3: RBAC -- "student" | "teacher"
        





def get_trivia(idx_of_trivia_set, question_idx): # TODO: make this secure. Include a passcode with every trivia set that only authorized users have.
    global trivia_sets
    with trivia_set_lock:
        if(question_idx>=trivia_sets[idx_of_trivia_set].num_questions):
            return False
        return trivia_sets[idx_of_trivia_set].get_question(question_idx)

def get_analytics(idx_of_trivia_set): # TODO: This should only be available to the creator of the trivia.
    global trivia_sets
    with trivia_set_lock:
        return trivia_sets[idx_of_trivia_set].analytics

def get_user(UUID):
    global users
    with users_lock:
        user = users[UUID]
        return {"username": user.username, "UUID": user.UUID, "role": user.role}
        ## DO NOT SEND PASSWORDS TO ANYBODY WHO ASKS -- password hash is
        ## intentionally left out of this dict.

def get_user_by_credentials(username, password):
    """
    J1: Looks up a user by username and verifies the supplied plaintext
    password against the stored bcrypt hash. Returns a safe (no password)
    dict on success, or None on any failure (unknown user OR wrong
    password) -- callers must not be able to distinguish the two, or that
    becomes a username-enumeration side channel.
    """
    global users
    with users_lock:
        match = next((u for u in users.values() if u.username == username), None)
    if match is None:
        return None
    if not verify_password(password, match.password):
        return None
    return {"username": match.username, "UUID": match.UUID, "role": match.role}

def verify_answer(UUID, idx_of_trivia_set, question_idx, answer):
    global trivia_sets
    with trivia_set_lock:
        
        result = trivia_sets[idx_of_trivia_set].verify_answer(question_idx, answer)
        if(result is True):
            trivia_sets[idx_of_trivia_set].analytics[question_idx]['correct']+=1
        else:
            trivia_sets[idx_of_trivia_set].analytics[question_idx]['incorrect']+=1
        trivia_sets[idx_of_trivia_set].analytics[question_idx]['responses']+=[(UUID, answer)]
        return result


def new_trivia_set(trivia_json):
    global trivia_sets
    with trivia_set_lock:
        trivia_sets+=[TriviaSet(trivia_json)]
        return len(trivia_sets)-1

def register_user(username, password, role="student"):
    """
    J1: password arrives here as plaintext from the client (over HTTPS)
    and is hashed with bcrypt before anything touches storage or memory
    longer-term. The plaintext value itself is never stored.
    """
    global users
    with users_lock:
        if any(map(lambda x: x.username==username, users.values())):
            return "username already taken"
        new_uuid = uuid.uuid4().hex
        password_hash = hash_password(password)
        users[new_uuid]=User(username, password_hash, new_uuid, role)
        return new_uuid


# --- Game room lobbies (Darren) ---------------------------------------------

def create_room(host_uuid, idx_of_trivia_set, pacing_mode="self"):
    """
    Teacher/host opens a lobby bound to an existing trivia set.
    Returns a public room view dict, or an error string.
    """
    global rooms, trivia_sets, users
    with trivia_set_lock:
        if idx_of_trivia_set < 0 or idx_of_trivia_set >= len(trivia_sets):
            return "trivia set not found"
    with users_lock:
        host = users.get(host_uuid)
        if host is None:
            return "host not found"
        host_name = host.username
        host_role = host.role
    with rooms_lock:
        code = generate_room_code(rooms.keys())
        room = make_room(host_uuid, idx_of_trivia_set, pacing_mode)
        room["players"][host_uuid] = {
            "username": host_name,
            "role": host_role,
            "joined_at": time.time(),
        }
        rooms[code] = room
        return public_room_view(code, room)


def join_room(room_code, player_uuid):
    """
    Student (or any logged-in user) joins an existing lobby by PIN.
    Returns a public room view dict, or an error string.
    """
    global rooms, users
    code = str(room_code).strip()
    with users_lock:
        player = users.get(player_uuid)
        if player is None:
            return "player not found"
        player_name = player.username
        player_role = player.role
    with rooms_lock:
        room = rooms.get(code)
        if room is None:
            return "room not found"
        if room["status"] == "ended":
            return "room has ended"
        room["players"][player_uuid] = {
            "username": player_name,
            "role": player_role,
            "joined_at": time.time(),
        }
        return public_room_view(code, room)


def get_room(room_code):
    global rooms
    code = str(room_code).strip()
    with rooms_lock:
        room = rooms.get(code)
        if room is None:
            return None
        return public_room_view(code, room)


def start_room(room_code, host_uuid):
    """Only the host may flip waiting -> active."""
    global rooms
    code = str(room_code).strip()
    with rooms_lock:
        room = rooms.get(code)
        if room is None:
            return "room not found"
        if room["host_uuid"] != host_uuid:
            return "only the host can start the room"
        room["status"] = "active"
        room["question_idx"] = 0
        return public_room_view(code, room)


def leave_room(room_code, player_uuid):
    global rooms
    code = str(room_code).strip()
    with rooms_lock:
        room = rooms.get(code)
        if room is None:
            return "room not found"
        room["players"].pop(player_uuid, None)
        # If the host leaves, end the session so stragglers don't hang.
        if player_uuid == room["host_uuid"]:
            room["status"] = "ended"
        return public_room_view(code, room)


@atexit.register
def goodbye(): #TODO: save trivia sets and users.
    pass


trivia_data_server.register('get_trivia', get_trivia)
trivia_data_server.register('verify_answer', verify_answer)
trivia_data_server.register('new_trivia_set', new_trivia_set)
trivia_data_server.register('register_user', register_user)
trivia_data_server.register('get_user', get_user)
trivia_data_server.register('get_user_by_credentials', get_user_by_credentials)
trivia_data_server.register('get_analytics', get_analytics)
trivia_data_server.register('create_room', create_room)
trivia_data_server.register('join_room', join_room)
trivia_data_server.register('get_room', get_room)
trivia_data_server.register('start_room', start_room)
trivia_data_server.register('leave_room', leave_room)

server= trivia_data_server.get_server()
server.serve_forever()
