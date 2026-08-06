# Testing Guide: Trivia App Backend

This walks through testing `server.py` + `trivia-manager.py` together on your
machine, using `smoke_test.py` to verify the whole flow end-to-end.

## Fixes verified by this test run

Four real issues were found and fixed since the last pass, all confirmed by
actually running `smoke_test.py` against a live server, not just by reading
the code:

1. **SUBMIT_ANSWER / GET_ANALYTICS method mismatch.** `server.py` declared
   `/api/trivia/verify` and `/api/trivia/analytics` as GET-only, but the
   real browser client sends POST (browsers can't attach a body to GET).
   The routes now accept both.
2. **Missing-field validation.** `create_user()` used to read
   `user_info['password']` directly, so an omitted field raised an
   unhandled 500 instead of a clean 400.
3. **Case-sensitive folder names.** Flask defaults to lowercase
   `templates`/`static` folders; this repo's folders are `Templates`/
   `Static`. That's invisible on Windows/macOS but 500'd the homepage and
   404'd `script.js` on Linux (i.e. Render, or any real deployment
   target). `server.py` now points Flask at the folders that actually
   exist.
4. **One shared HMAC secret, replaced with per-session tokens.** Every
   browser used to sign requests with the same static `TRIVIA_HMAC_SECRET`
   baked into `Static/script.js` -- readable by anyone who opened dev
   tools, and identical for every user this app has ever had. Login and
   registration now issue a fresh, random signing token per session
   instead (see `security.py`'s `issue_login_session()`), returned in the
   response body. `smoke_test.py` proves this actually matters, not just
   that it's "more secure" in the abstract: a request signed with one
   session's token but sent as another session is rejected (see the
   "signed with a DIFFERENT session's token is rejected" check below).

## Files you need in the same folder

- `server.py`
- `trivia-manager.py`
- `security.py`
- `reliability.py`
- `answer_normalize.py`
- `smoke_test.py` (the test script)

## 0. One-time setup

Install dependencies:

```powershell
py -m pip install flask bcrypt
```
(macOS/Linux: `python3 -m pip install flask bcrypt`)

## 1. Open three terminal windows, all in the same folder

No shared secret to set up anymore -- signing tokens are issued per
session automatically at login, so there's nothing to keep in sync
across terminals. Just `cd` into the folder in each of the three windows:

**Windows (PowerShell):**
```powershell
cd "C:\path\to\your\folder"
```

**macOS/Linux:**
```bash
cd /path/to/your/folder
```

## 2. Terminal 1 — start the backend manager

```powershell
py trivia-manager.py

```

Leave this running. No output means it's working — it's just sitting there
listening on port 5555.

## 3. Terminal 2 — start the web server

Only do this **after** Terminal 1 is up and running.

```powershell
py -m flask --app server run --port 8000
```

You should see:

```
* Running on http://127.0.0.1:8000
Press CTRL+C to quit
```

Leave this running too.

## 4. Terminal 3 — run the smoke test

```powershell
py smoke_test.py
```

Expected output:

```
[PASS] register teacher (201)
[PASS] register response includes a per-session signing_token
[PASS] login teacher (200, role=teacher)
[PASS] login response also includes a signing_token
[PASS] register missing password -> clean 400 (not 500)
[PASS] create trivia set (200), signed with teacher's per-session token
[PASS] get_analytics via POST (200, 2 empty entries)
[PASS] register student (201)
[PASS] login student (200, role=student)
[PASS] register second student (201)
[PASS] login second student (200)
[PASS] request signed with a DIFFERENT session's token is rejected (400)
[PASS] create room (201, has room_code)
[PASS] student join room (200)
[PASS] second student join room (200)
[PASS] get room roster includes 3 players (host + 2 students)
[PASS] start room (200, status=active)
[PASS] get question 0 (200)
[PASS] no answer key leaked
[PASS] verify answer q0 correct, signed with student's own per-session token
[PASS] connectivity shows student as NOT connected before first heartbeat
[PASS] student heartbeat (200, PONG)
[PASS] connectivity flips to connected after heartbeat
[PASS] reconnect (200) also hands back a signing_token for this session
[PASS] create host-paced room (201)
[PASS] student joins host-paced room (200)
[PASS] start host-paced room (200)
[PASS] student sees question 0 in host-paced room
[PASS] student cannot self-advance in host-paced room (403)
[PASS] host advances room via ADVANCE_ROOM (200)
[PASS] student sees question 1 after host advanced (host-paced sync)
[PASS] student's answer graded against the CURRENT (post-advance) question

ALL PASSED
```

Note on why this matters more than it looks: SUBMIT_ANSWER and GET_ANALYTICS
are called here with **POST**, not GET, even though the protocol doc lists
GET first. That's deliberate -- POST is what the real browser client
(`Static/script.js`) actually sends, since browsers can't attach a body to
a GET/HEAD request. An earlier version of this test used GET, which is what
Python's request libraries will happily send regardless of what the server
declares -- so it kept passing even while the real frontend's POST calls
were 405ing against the server and silently falling back to local-only
grading. If you're extending this script, always match the method the real
client uses, not just "a method that works."

Also note the "signed with a DIFFERENT session's token is rejected" check.
That's the actual point of the per-session signing token change: it's not
enough for a signature to just be valid-looking, it has to be valid *for
that specific session*. A shared static secret couldn't tell the
difference between "the real teacher" and "anyone else who read the JS" --
a per-session token can.

## Running it again

The manager keeps everything (users, trivia sets) **in memory only**. If you
run the smoke test twice without restarting Terminals 1 and 2, it'll fail on
registration with "username already taken" -- though this version appends a
timestamp to every generated username, so back-to-back runs against the
same live backend should still get fresh usernames automatically.

To re-test cleanly anyway:
1. `Ctrl+C` in Terminal 1 and Terminal 2
2. Re-run the commands from steps 2 and 3
3. Re-run the smoke test in Terminal 3

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'server'` | Not in the right folder | `cd` into the folder that actually contains `server.py` (check with `Get-ChildItem`) |
| `ConnectionRefusedError` / `URLError` when running `smoke_test.py` | `server.py` (or `trivia-manager.py`) isn't actually running yet | Check Terminals 1 and 2 are still open and showing they're running, not back at a prompt |
| `Could not connect to the trivia-manager backend...` from `server.py` | Terminal 1 wasn't started first, or crashed | Start Terminal 1 before Terminal 2; check Terminal 1 for errors |
| `invalid or missing payload signature` | Signing a request before logging in (no token yet), or reusing a token across two different client sessions | Make sure `req(..., sign_body=True)` runs after a successful register/login for that same client |
| `RuntimeError: no signing token available` | Tried to sign a request before that client had registered/logged in | Register or log in that client first -- signing tokens only exist after a successful auth call |
| `"username already taken"` failures | Re-running without restarting the backend, or a suffix collision | See "Running it again" above |
| `ModuleNotFoundError: No module named 'bcrypt'` or `'flask'` | Dependency not installed | `py -m pip install bcrypt flask` |

## What the smoke test actually checks

`smoke_test.py` talks to the real running server over HTTP (not by importing
your code), so it's a true end-to-end check, covering:

- Teacher and student registration and login
- Creating a trivia set (with a signed request)
- Fetching analytics for a fresh set
- Fetching a question and confirming the answer key isn't leaked to the client
- Verifying a correct short-answer response
- Verifying a correct multiple-select response
- Advancing to the next question
- Reaching the end of the quiz without crashing
