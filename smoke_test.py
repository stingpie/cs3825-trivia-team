"""
smoke_test.py

Exercises the full trivia app flow against a LOCALLY RUNNING instance:
    terminal 1: python3 trivia-manager.py
    terminal 2: python3 -m flask --app server run --port 8000
    terminal 3: python3 smoke_test.py

Requires: TRIVIA_HMAC_SECRET to be set to the SAME value server.py/
trivia-manager.py are using, so this script can sign requests the same
way a real client would.

This does not import server.py or trivia-manager.py -- it only talks to
them over HTTP, exactly like a real client, so it's a true end-to-end
check rather than a test of internal functions.
"""

import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

BASE_URL = "http://localhost:8000"
HMAC_SECRET = os.environ.get("TRIVIA_HMAC_SECRET", "").encode("utf-8")

if not HMAC_SECRET:
    print("ERROR: set TRIVIA_HMAC_SECRET to the same value the server is using.")
    sys.exit(1)

import hmac
import hashlib


def sign(body_bytes: bytes) -> str:
    return hmac.new(HMAC_SECRET, body_bytes, hashlib.sha256).hexdigest()


def make_client():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def req(method, path, body=None, sign_body=False):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if sign_body:
            r.add_header("X-Signature", sign(data or b""))
        try:
            resp = opener.open(r)
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw or "null")
            except json.JSONDecodeError:
                return resp.status, raw  # plain-text response (e.g. create_user's "new user created!")
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw or "null")
            except json.JSONDecodeError:
                return e.code, raw

    return req


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


def main():
    ok = True
    teacher = make_client()
    student = make_client()

    # --- Teacher: register + login ---
    status, body = teacher("POST", "/api/users", {
        "username": "ms_smith", "password": "hunter2", "role": "teacher"
    })
    ok &= check("register teacher (201)", status == 201)

    status, body = teacher("POST", "/api/login", {
        "username": "ms_smith", "password": "hunter2"
    })
    ok &= check("login teacher (200, role=teacher)", status == 200 and body.get("role") == "teacher")

    # --- Teacher: create a trivia set (signed request) ---
    quiz = [
        {"type": "short answer", "question": "Who was the first US president?",
         "correct answers": ["George Washington"]},
        {"type": "multiple select", "question": "Factors of 6?",
         "possible responses": ["2", "3", "4"], "correct answers": ["2", "3"]},
    ]
    status, body = teacher("POST", "/api/trivia", quiz, sign_body=True)
    ok &= check("create trivia set (200)", status == 200)

    # --- Teacher: analytics for the fresh set should be all zeros ---
    status, body = teacher("GET", "/api/trivia/analytics", {"idx_of_trivia_set": 0})
    ok &= check("get_analytics (200, 2 empty entries)",
                status == 200 and isinstance(body, list) and len(body) == 2)

    # --- Student: register + login ---
    status, body = student("POST", "/api/users", {
        "username": "bobby", "password": "pw12345", "role": "student"
    })
    ok &= check("register student (201)", status == 201)

    status, body = student("POST", "/api/login", {
        "username": "bobby", "password": "pw12345"
    })
    ok &= check("login student (200, role=student)", status == 200 and body.get("role") == "student")

    # --- Student: fetch question 0, confirm no answer leak ---
    status, body = student("GET", "/api/trivia")
    ok &= check("get question 0 (200)", status == 200)
    ok &= check("no answer key leaked", "correct answers" not in body)

    # --- Student: submit correct answer ---
    payload = {"answer": ["George Washington"]}
    status, body = student("GET", "/api/trivia/verify", payload, sign_body=True)
    ok &= check("verify answer q0 correct", status == 200 and body.get("correct") is True)

    # --- Student: advance to question 1 ---
    status, body = student("GET", "/api/trivia/next")
    ok &= check("advance to question 1 (200)", status == 200 and "possible responses" in body)

    # --- Student: submit correct multi-select answer ---
    payload = {"answer": ["2", "3"]}
    status, body = student("GET", "/api/trivia/verify", payload, sign_body=True)
    ok &= check("verify answer q1 correct", status == 200 and body.get("correct") is True)

    # --- Student: advance past the end of the quiz ---
    status, body = student("GET", "/api/trivia/next")
    ok &= check("reach end of quiz gracefully (200, done=true)",
                status == 200 and body.get("done") is True)

    print()
    print("ALL PASSED" if ok else "SOME CHECKS FAILED -- see [FAIL] lines above")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
