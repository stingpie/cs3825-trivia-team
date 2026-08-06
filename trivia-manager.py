from multiprocessing import Lock
from multiprocessing.managers import BaseManager
import atexit
import pickle
import os
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


# --- Persistence (accounts + quizzes survive a process restart) ------------
# users and trivia_sets previously lived ONLY in memory -- every restart
# (crash, manual restart, or a Render redeploy) silently wiped every
# registered account and every saved quiz, with no error to explain why.
# This pickles both to a local file after every mutation, and reloads them
# on startup. Rooms are intentionally NOT persisted: a live lobby's value
# ends when the process restarts anyway (every connected client would need
# to reconnect and re-join from scratch), so keeping that in memory only
# avoids resurrecting stale, half-broken room state.
#
# Caveat: this is a local file, not a database. It survives restarts and
# crashes on the same machine/container. It does NOT survive a fresh
# Render deploy, since Render gives each deploy a new, empty disk unless
# you've attached a persistent disk volume. For anything that needs to
# survive redeploys, this file needs to be swapped for real external
# storage (e.g. a small hosted Postgres/SQLite-on-a-volume) later.
DATA_FILE = os.environ.get("TRIVIA_DATA_FILE", "trivia_data.pkl")


def _save_state():
    try:
        with trivia_set_lock, users_lock:
            snapshot = {"users": users, "trivia_sets": trivia_sets}
        tmp_path = DATA_FILE + ".tmp"
        with open(tmp_path, "wb") as f:
            pickle.dump(snapshot, f)
        os.replace(tmp_path, DATA_FILE)  # atomic on POSIX -- avoids a half-written file if the process dies mid-save
    except Exception as exc:
        print(f"[trivia-manager.py] WARNING: failed to save state: {exc!r}")


def _load_state():
    global users, trivia_sets
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "rb") as f:
            snapshot = pickle.load(f)
        users = snapshot.get("users", {})
        trivia_sets = snapshot.get("trivia_sets", [])
        print(f"[trivia-manager.py] Restored {len(users)} user(s) and "
              f"{len(trivia_sets)} trivia set(s) from {DATA_FILE}.")
    except Exception as exc:
        print(f"[trivia-manager.py] WARNING: failed to load {DATA_FILE} "
              f"({exc!r}); starting with empty state.")


# -----------------------------------------------------------------------------


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
        # J-fix: the client had no way to render an accurate "Question X of Y"
        # badge for live (non-fallback) sessions -- it only had the question
        # text/type/choices. Include the position so script.js's loadMultiplayerQuestion()
        # can update #question-progress-badge on every question, not just the
        # local-fallback path.
        ret['question_idx'] = index
        ret['num_questions'] = self.num_questions
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
        idx = len(trivia_sets)-1
    _save_state()
    return idx

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
    _save_state()
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


def advance_room_question(room_code, host_uuid):
    """
    Host-only: advances the room's shared question_idx by one. In
    host-paced mode this is the single source of truth every player reads
    from (see get_trivia() in server.py), so this is what actually makes
    "Next Question" show the next question to everyone in the room at
    once, instead of just the host's own session.
    """
    global rooms
    code = str(room_code).strip()
    with rooms_lock:
        room = rooms.get(code)
        if room is None:
            return "room not found"
        if room["host_uuid"] != host_uuid:
            return "only the host can advance the room"
        if room["status"] != "active":
            return "room is not active"
        room["question_idx"] += 1
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
def goodbye():
    _save_state()


# Load any previously saved users/trivia sets now that User and TriviaSet
# are defined -- must happen after both classes exist, or pickle can't
# reconstruct saved instances of them.
_load_state()

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
trivia_data_server.register('advance_room_question', advance_room_question)
trivia_data_server.register('leave_room', leave_room)

server= trivia_data_server.get_server()
server.serve_forever()
