"""
smoke_test.py

Exercises the full trivia app flow against a LOCALLY RUNNING instance:
    terminal 1: python3 trivia-manager.py
    terminal 2: python3 -m flask --app server run --port 8000
    terminal 3: python3 smoke_test.py

This does not import server.py or trivia-manager.py -- it only talks to
them over HTTP, exactly like a real client, so it's a true end-to-end
check rather than a test of internal functions.

No shared secret to configure. Signing requests used to require setting
TRIVIA_HMAC_SECRET to the same value in every terminal; that's gone now,
because signing switched from one static secret shared by every browser
to a fresh, random token issued per-session at login/register (see
security.py's issue_login_session()). This script captures that token
from each client's own login/register response, exactly the way
Static/script.js does, and signs with it -- proving the real client flow
works, not just that "a signature" was accepted somewhere.

IMPORTANT: SUBMIT_ANSWER and GET_ANALYTICS are called with POST here,
not GET, even though the protocol doc lists GET first. That's deliberate:
POST is what the real browser client (Static/script.js) actually sends,
because browsers cannot attach a body to a GET/HEAD request at all. An
earlier version of this script used GET, which matches what Python's
request libraries will happily send -- and because of that, it kept
passing even after server.py's routes only accepted GET, silently
missing that the real frontend's POST calls were getting a 405 the whole
time. Testing with the same method the real client uses is what catches
that class of bug; testing with "a valid method" is not the same thing.
See the Deliverable 2 report, Section 7 ("Integration Testing"), for how
this was found.
"""

import hashlib
import hmac
import json
import sys
import time
import urllib.request
import urllib.error
import http.cookiejar

BASE_URL = "http://localhost:8000"


def sign(token: str, body_bytes: bytes) -> str:
    return hmac.new(token.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def make_client():
    """
    Returns a req(method, path, body=None, sign_body=False) function with
    its own cookie jar (so it behaves like one browser / one logged-in
    session) and its own signing_token, captured automatically whenever
    a register/login response includes one -- just like currentSigningToken
    in Static/script.js.
    """
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    state = {"signing_token": None}

    def req(method, path, body=None, sign_body=False, sign_with=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if sign_body:
            token = sign_with if sign_with is not None else state["signing_token"]
            if not token:
                raise RuntimeError(f"no signing token available for {method} {path} -- log in first")
            r.add_header("X-Signature", sign(token, data or b""))
        try:
            resp = opener.open(r)
            raw = resp.read().decode()
            status, parsed = resp.status, json.loads(raw or "null")
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                status, parsed = e.code, json.loads(raw or "null")
            except json.JSONDecodeError:
                status, parsed = e.code, raw

        # Auto-capture the per-session signing token off any response
        # that carries one, the same way apiRegisterUser()/apiLoginUser()
        # do in Static/script.js.
        if isinstance(parsed, dict) and parsed.get("signing_token"):
            state["signing_token"] = parsed["signing_token"]

        return status, parsed

    req.signing_token = lambda: state["signing_token"]
    return req


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


def main():
    ok = True
    suffix = str(int(time.time()))  # avoid "username already taken" on repeat runs
    teacher = make_client()
    student = make_client()
    student2 = make_client()

    # --- Teacher: register + login ---
    status, body = teacher("POST", "/api/users", {
        "username": f"ms_smith_{suffix}", "password": "hunter2", "role": "teacher"
    })
    ok &= check("register teacher (201)", status == 201)
    ok &= check("register response includes a per-session signing_token",
                bool(teacher.signing_token()))

    status, body = teacher("POST", "/api/login", {
        "username": f"ms_smith_{suffix}", "password": "hunter2"
    })
    ok &= check("login teacher (200, role=teacher)", status == 200 and body.get("role") == "teacher")
    ok &= check("login response also includes a signing_token", bool(body.get("signing_token")))

    # --- Invalid input: register with a missing field should be a clean 400, not a 500 ---
    status, body = teacher("POST", "/api/users", {"username": "no_password_here"})
    ok &= check("register missing password -> clean 400 (not 500)", status == 400)

    # --- Teacher: create a trivia set (signed with the teacher's own session token) ---
    quiz = [
        {"type": "short answer", "question": "Who was the first US president?",
         "correct answers": ["George Washington"]},
        {"type": "multiple select", "question": "Factors of 6?",
         "possible responses": ["2", "3", "4"], "correct answers": ["2", "3"]},
    ]
    status, body = teacher("POST", "/api/trivia", quiz, sign_body=True)
    ok &= check("create trivia set (200), signed with teacher's per-session token", status == 200)

    # --- Teacher: analytics for the fresh set should be all zeros ---
    # POST, not GET: this is the actual method the browser client sends
    # (see module docstring). If this route only accepted GET, this
    # would 405 here exactly like it does for the real frontend.
    status, body = teacher("POST", "/api/trivia/analytics", {"idx_of_trivia_set": 0})
    ok &= check("get_analytics via POST (200, 2 empty entries)",
                status == 200 and isinstance(body, list) and len(body) == 2)

    # --- Student: register + login ---
    status, body = student("POST", "/api/users", {
        "username": f"bobby_{suffix}", "password": "pw12345", "role": "student"
    })
    ok &= check("register student (201)", status == 201)

    status, body = student("POST", "/api/login", {
        "username": f"bobby_{suffix}", "password": "pw12345"
    })
    ok &= check("login student (200, role=student)", status == 200 and body.get("role") == "student")

    # --- Second student, for multi-host / lobby testing ---
    status, body = student2("POST", "/api/users", {
        "username": f"casey_{suffix}", "password": "pw12345", "role": "student"
    })
    ok &= check("register second student (201)", status == 201)
    status, body = student2("POST", "/api/login", {
        "username": f"casey_{suffix}", "password": "pw12345"
    })
    ok &= check("login second student (200)", status == 200)

    # --- Token isolation: signing with a DIFFERENT session's token must fail ---
    # This is the actual point of moving off one shared secret. If the
    # server only checked "is this a valid-looking signature" instead of
    # "is this THIS session's own token", a leaked token would still let
    # an attacker forge requests for every user, not just the one it was
    # issued to -- exactly the property the old shared-secret design didn't
    # have. Prove it holds: sign a teacher-only request with the student's
    # token instead of the teacher's own, and confirm it's rejected.
    status, body = teacher("POST", "/api/trivia", quiz,
                            sign_body=True, sign_with=student.signing_token())
    ok &= check("request signed with a DIFFERENT session's token is rejected (400)",
                status == 400)

    # --- Lobby flow: teacher hosts a self-paced room, two students join by PIN ---
    status, body = teacher("POST", "/api/rooms", {
        "idx_of_trivia_set": 0, "pacing_mode": "self"
    })
    room_ok = status == 201 and isinstance(body, dict) and "room_code" in body
    ok &= check("create room (201, has room_code)", room_ok)
    room_code = body.get("room_code") if room_ok else None

    if room_code:
        status, body = student("POST", "/api/rooms/join", {"room_code": room_code})
        ok &= check("student join room (200)",
                    status == 200 and body.get("room_code") == room_code)

        status, body = student2("POST", "/api/rooms/join", {"room_code": room_code})
        ok &= check("second student join room (200)",
                    status == 200 and body.get("room_code") == room_code)

        status, body = teacher("GET", f"/api/rooms/{room_code}")
        ok &= check("get room roster includes 3 players (host + 2 students)",
                    status == 200 and body.get("player_count", 0) >= 3)

        status, body = teacher("POST", f"/api/rooms/{room_code}/start")
        ok &= check("start room (200, status=active)",
                    status == 200 and body.get("status") == "active")

        # --- Student: fetch question 0, confirm no answer leak ---
        status, body = student("GET", "/api/trivia")
        ok &= check("get question 0 (200)", status == 200)
        ok &= check("no answer key leaked", "correct answers" not in body)

        # --- Student: submit correct answer, signed with the STUDENT's own token ---
        payload = {"answer": ["George Washington"]}
        status, body = student("POST", "/api/trivia/verify", payload, sign_body=True)
        ok &= check("verify answer q0 correct, signed with student's own per-session token",
                    status == 200 and body.get("correct") is True)

        # --- Connectivity: student hasn't heartbeat'd yet -- should show disconnected ---
        status, body = teacher("GET", f"/api/rooms/{room_code}/connectivity")
        players = body.get("players", []) if status == 200 else []
        student_conn = next((p for p in players if p.get("username", "").startswith("bobby")), None)
        ok &= check("connectivity shows student as NOT connected before first heartbeat",
                    status == 200 and student_conn is not None and student_conn.get("connected") is False)

        # --- Student sends a heartbeat, connectivity should flip to true ---
        status, body = student("POST", "/api/heartbeat")
        ok &= check("student heartbeat (200, PONG)", status == 200 and body.get("type") == "PONG")

        status, body = teacher("GET", f"/api/rooms/{room_code}/connectivity")
        players = body.get("players", []) if status == 200 else []
        student_conn = next((p for p in players if p.get("username", "").startswith("bobby")), None)
        ok &= check("connectivity flips to connected after heartbeat",
                    status == 200 and student_conn is not None and student_conn.get("connected") is True)

        # --- Reconnect flow: confirm the signing token comes back too, not just quiz progress ---
        status, body = student("GET", "/api/reconnect")
        ok &= check("reconnect (200) also hands back a signing_token for this session",
                    status == 200 and bool(body.get("signing_token")))

    # --- Host-paced room: teacher controls advancement for every player at once ---
    status, body = teacher("POST", "/api/rooms", {
        "idx_of_trivia_set": 0, "pacing_mode": "host"
    })
    hp_ok = status == 201 and isinstance(body, dict) and "room_code" in body
    ok &= check("create host-paced room (201)", hp_ok)
    hp_code = body.get("room_code") if hp_ok else None

    if hp_code:
        status, body = student2("POST", "/api/rooms/join", {"room_code": hp_code})
        ok &= check("student joins host-paced room (200)", status == 200)

        status, body = teacher("POST", f"/api/rooms/{hp_code}/start")
        ok &= check("start host-paced room (200)", status == 200)

        status, body = student2("GET", "/api/trivia")
        q0_ok = status == 200 and "question" in body
        ok &= check("student sees question 0 in host-paced room", q0_ok)

        # A self-advance attempt should be rejected in host-paced mode
        status, body = student2("GET", "/api/trivia/next")
        ok &= check("student cannot self-advance in host-paced room (403)", status == 403)

        # The host advances the room for everyone
        status, body = teacher("POST", f"/api/rooms/{hp_code}/next")
        ok &= check("host advances room via ADVANCE_ROOM (200)",
                    status == 200 and body.get("question_idx") == 1)

        # Student should now see question 1 without having advanced themselves,
        # AND grading should be against question 1, not the stale question 0 --
        # this specifically covers the stale-grading bug found in Deliverable 2.
        status, body = student2("GET", "/api/trivia")
        ok &= check("student sees question 1 after host advanced (host-paced sync)",
                    status == 200 and body.get("question_idx") == 1)

        payload = {"answer": ["2", "3"]}
        status, body = student2("POST", "/api/trivia/verify", payload, sign_body=True)
        ok &= check("student's answer graded against the CURRENT (post-advance) question",
                    status == 200 and body.get("correct") is True)

    print()
    print("ALL PASSED" if ok else "SOME CHECKS FAILED -- see [FAIL] lines above")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
