# Custom Application Protocol Specification
**Author:** Darren Robinson — Networking & Real-Time Sync Lead  
**Project:** Educational Trivia Platform (COMP 3825)

This document defines the application-layer protocol used by our trivia
system. Clients (browser JavaScript) and the Flask front server
(`server.py`) exchange JSON messages over HTTP. `server.py` then talks
to the shared data process (`trivia-manager.py`) over a local
multiprocessing manager channel on port 5555.

---

## 1. Transport & Framing

| Layer | Choice |
|---|---|
| Transport | TCP / HTTP 1.1 |
| Encoding | UTF-8 JSON request/response bodies |
| Session identity | Flask signed cookie session (`UUID`, `role`, trivia progress) |
| Integrity (writes) | HMAC-SHA256 hex digest in `X-Signature` header, keyed by a per-session signing token |
| Heartbeat interval | Client sends PING every 5 seconds |
| Heartbeat timeout | Server marks client disconnected after 15 seconds (3 missed beats) |

All mutating or answer-sensitive requests must include:

```
X-Signature: <hmac_sha256_hex(raw_request_body, this_session's_signing_token)>
Content-Type: application/json
```

The signing token is **not** a static secret shared by every client. It is
generated fresh, at random, per session, by `issue_login_session()` in
`security.py`, and returned in the response body of a successful
REGISTER_USER or LOGIN call (see 2.1 and 2.2 below). The client stores it
in memory for that session only and uses it to sign every write-sensitive
request from then on. This replaced an earlier design where one static
secret was embedded directly in `Static/script.js` and shared by every
browser -- readable by anyone who opened dev tools, and identical for
every user the app has ever had. A leaked per-session token only affects
the one session it was issued to; `smoke_test.py` includes a check that
specifically proves a request signed with a *different* session's token
is rejected, not just that "some" signature is accepted.

---

## 2. Message Catalog

For each message: name, purpose, required fields, success response,
and error response — matching the course protocol documentation
requirements.

### 2.1 REGISTER_USER

**Purpose:** Create a new student or teacher account.

**Endpoint:** `POST /api/users`

**Required fields:**
```json
{
  "username": "bobby",
  "password": "pw12345",
  "role": "student"
}
```
`role` is optional and defaults to `"student"`. Allowed values:
`"student"` | `"teacher"`.

**Success response:** HTTP `201`
```json
{ "message": "new user created!", "signing_token": "<random per-session token>" }
```
Session cookie is issued with `UUID` and `role`. `signing_token` is a
fresh, random value generated for this session -- store it and use it to
sign every write-sensitive request from here on (see Section 1). It is
**not** a fixed secret; a different login gets a different token, even
for the same account.

**Error response:** HTTP `400` — missing `username` or `password`, or HTTP `409` — `"username already taken"`

---

### 2.2 LOGIN

**Purpose:** Authenticate an existing user and establish a session.

**Endpoint:** `POST /api/login`

**Required fields:**
```json
{
  "username": "ms_smith",
  "password": "hunter2"
}
```

**Success response:**
```json
{ "role": "teacher", "signing_token": "<random per-session token>" }
```
HTTP `200`. Session cookie issued, and a fresh `signing_token` for this
session -- the previous session's token (if any) is no longer valid once a
new one is issued, since `require_valid_signature` always checks against
whatever the current session's `signing_token` is.

**Error response:**
```json
{ "error": "invalid username or password" }
```
HTTP `401`.

---

### 2.3 CREATE_TRIVIA

**Purpose:** Teacher uploads a new quiz (JSON question set).

**Endpoint:** `POST /api/trivia`  
**Auth:** logged-in `teacher` role + valid `X-Signature`

**Required fields:** a JSON array of question objects (see §3).

**Success response:** HTTP `200` — string index of the new trivia set
(e.g. `"0"`).

**Error responses:**
- `401` `{ "error": "not authenticated" }`
- `403` `{ "error": "forbidden: insufficient role" }`
- `400` `{ "error": "invalid or missing payload signature" }`

---

### 2.4 GET_QUESTION

**Purpose:** Fetch the current question for the student's session
without revealing the answer key.

**Endpoint:** `GET /api/trivia`  
**Auth:** logged-in session

**Required fields:** none in body — progress comes from session
(`idx_of_trivia_set`, `question_idx`).

**Success response:**
```json
{
  "type": "short answer",
  "question": "Who was the first US president?",
  "possible responses": null
}
```
(`correct answers` is stripped server-side.)

**Error responses:**
- `401` not authenticated
- `400` `"No active trivia set selected."` / `"No question index found"`
- `500` `"Error in getting the next question."`

---

### 2.5 SUBMIT_ANSWER

**Purpose:** Grade a student's answer for the current question.

**Endpoint:** `GET or POST /api/trivia/verify`  
**Auth:** logged-in session + valid `X-Signature`

Both methods are accepted: `GET` per the original protocol design (used by
non-browser clients, e.g. the test scripts in this repo), and `POST` because
browsers cannot attach a body to a `GET`/`HEAD` request at all — the real
front-end client (`Static/script.js`) always sends `POST`. This route used
to declare `GET` only, which meant the actual browser client's request was
silently rejected with `405` and fell back to grading the answer locally;
see the Deliverable 2 report, Section 3 ("Known Protocol Deviation") and
Section 7 ("Integration Testing"), for how this was found and fixed.

**Required fields:**
```json
{ "answer": ["George Washington"] }
```
For multiple-select, `answer` is an array of all chosen options.

**Success response:**
```json
{ "correct": true }
```
or `{ "correct": false }` — HTTP `200`.

**Error responses:**
- `400` invalid/missing HMAC signature
- `400` missing trivia session fields
- `401` not authenticated

---

### 2.6 NEXT_QUESTION

**Purpose:** Advance the student one question forward (never backward).

**Endpoint:** `GET /api/trivia/next`  
**Auth:** logged-in session

**Success response:** next question object (same shape as GET_QUESTION),
or when the quiz ends:
```json
{ "done": true, "message": "You've reached the end of the quiz." }
```

**Error responses:** `400` / `401` as above.

---

### 2.7 GET_ANALYTICS

**Purpose:** Teacher views per-question correctness stats for a set.

**Endpoint:** `GET or POST /api/trivia/analytics`  
**Auth:** logged-in `teacher` role

Both methods are accepted for the same reason as SUBMIT_ANSWER above:
`Static/script.js`'s `exportStudentGrades()` sends `POST` since a browser
can't attach a body to `GET`.

**Required fields:**
```json
{ "idx_of_trivia_set": 0 }
```

**Success response:**
```json
[
  { "correct": 3, "incorrect": 1, "responses": [["uuid", ["ans"]]] },
  { "correct": 2, "incorrect": 2, "responses": [] }
]
```

**Error responses:** `401` / `403` for auth/role failures.

---

### 2.8 HEARTBEAT (PING / PONG)

**Purpose:** Detect live vs. dropped clients every 5 seconds.

**Endpoint:** `POST /api/heartbeat`  
**Auth:** logged-in session

**Required fields (client → server):**
```json
{ "type": "PING", "timestamp": 1722700000 }
```

**Success response (server → client):**
```json
{ "type": "PONG", "timestamp": 1722700001 }
```

If three consecutive intervals are missed (15s), the server treats the
client as disconnected via `is_connected(uuid)` /
`get_disconnected_users()`.

---

### 2.9 RECONNECT

**Purpose:** After a temporary network drop, restore quiz progress
using the existing session token instead of restarting at question 0.

**Endpoint:** `GET /api/reconnect`  
**Auth:** logged-in session

**Success response:**
```json
{
  "idx_of_trivia_set": 0,
  "question_idx": 2,
  "room_code": null,
  "saved_at": 1722700123.45
}
```
Session progress fields are rewritten to match.

**Error response:**
```json
{ "error": "no saved progress for this session" }
```
HTTP `404`.

---

### 2.10 CREATE_ROOM

**Purpose:** Teacher opens a game lobby bound to a trivia set and gets a
4-digit PIN for students to join (matches the frontend Host / Join Room UI).

**Endpoint:** `POST /api/rooms`  
**Auth:** logged-in `teacher` role

**Required fields:**
```json
{ "idx_of_trivia_set": 0, "pacing_mode": "self" }
```
`pacing_mode` is optional (`"self"` | `"host"`).

**Success response:** HTTP `201`
```json
{
  "room_code": "4821",
  "host_uuid": "...",
  "status": "waiting",
  "player_count": 1,
  "players": [{"UUID": "...", "username": "ms_smith", "role": "teacher"}]
}
```

**Error responses:** `404` trivia set / host not found; `401` / `403` auth.

---

### 2.11 JOIN_ROOM

**Purpose:** Student enters the host's PIN to join the lobby.

**Endpoint:** `POST /api/rooms/join`  
**Auth:** logged-in session

**Required fields:**
```json
{ "room_code": "4821" }
```

**Success response:** HTTP `200` — same public room shape as CREATE_ROOM.  
Session is bound to that trivia set / room for later GET_QUESTION calls.

**Error responses:** `404` room not found; `409` ended.

---

### 2.12 GET_ROOM / START_ROOM / LEAVE_ROOM

| Message | Endpoint | Purpose |
|---|---|---|
| GET_ROOM | `GET /api/rooms/<code>` | Poll roster and status |
| START_ROOM | `POST /api/rooms/<code>/start` | Host flips `waiting` → `active` |
| LEAVE_ROOM | `POST /api/rooms/leave` | Leave current lobby |

---

## 3. Quiz JSON Schema (application payload)

A trivia set is a JSON array. Each element is one of:

**Short answer**
```json
{
  "type": "short answer",
  "question": "Who was the first president of the US?",
  "correct answers": ["George Washington", "President George Washington"]
}
```

**Multiple choice**
```json
{
  "type": "multiple choice",
  "question": "What is the role of RAM in a computer?",
  "possible responses": ["long term storage", "processing math", "audio", "fast temporary storage"],
  "correct answers": ["fast temporary storage"]
}
```

**Multiple select**
```json
{
  "type": "multiple select",
  "question": "What are the factors of 6?",
  "possible responses": ["12", "2", "4", "3"],
  "correct answers": ["2", "3"]
}
```

Short answers are graded after normalization (case, whitespace, minor
punctuation) so conceptually correct replies are not rejected for
formatting alone.

---

## 4. Example Message Flow

```
Student                         Server                         Teacher
   |                              |                               |
   |--- REGISTER_USER ----------->|                               |
   |<-- 201 + session cookie -----|                               |
   |                              |<------ REGISTER_USER ---------|
   |                              |------- 201 + cookie --------->|
   |                              |<------ LOGIN -----------------|
   |                              |------- {role:teacher} ------->|
   |                              |<------ CREATE_TRIVIA + HMAC --|
   |                              |------- set index "0" -------->|
   |                              |<------ CREATE_ROOM -----------|
   |                              |------- PIN "4821" ----------->|
   |--- LOGIN ------------------->|                               |
   |<-- {role:student} -----------|                               |
   |--- JOIN_ROOM {4821} -------->|                               |
   |<-- lobby roster -------------|                               |
   |                              |<------ START_ROOM ------------|
   |                              |------- status=active -------->|
   |--- GET_QUESTION ------------>|                               |
   |<-- question (no key) --------|                               |
   |--- SUBMIT_ANSWER + HMAC ---->|                               |
   |<-- {correct:true} -----------|                               |
   |--- NEXT_QUESTION ----------->|                               |
   |<-- next question / done -----|                               |
   |--- PING (every 5s) --------->|                               |
   |<-- PONG ---------------------|                               |
   |   (Wi-Fi drops...)           |                               |
   |--- RECONNECT --------------->|                               |
   |<-- saved question index -----|                               |
```

---

## 5. Internal Host-to-Host Channel

Between `server.py` (host A front door) and `trivia-manager.py`
(host A data process, portable to a second machine):

- Address: `localhost:5555` (configurable to another host IP for
  multi-host demos)
- Auth key: shared bytes `b'trivia'`
- RPCs: `register_user`, `get_user_by_credentials`, `new_trivia_set`,
  `get_trivia`, `verify_answer`, `get_analytics`, `get_user`

This split lets multiple browser clients on separate machines share one
authoritative trivia/analytics store while the Flask layer keeps
per-client sessions and protocol enforcement.
