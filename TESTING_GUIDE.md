# Testing Guide: Trivia App Backend

This walks through testing `server.py` + `trivia-manager.py` together on your
machine, using `smoke_test.py` to verify the whole flow end-to-end.

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

## 1. Open three PowerShell windows, all in the same folder

In **each** of the three windows:

```powershell
cd "C:\path\to\your\folder"
$env:TRIVIA_HMAC_SECRET = "Jordan"
```

> Use the exact same secret string in all three windows. It doesn't need to
> be fancy for local testing — it just has to match everywhere, since it's
> used to sign and verify requests between the client and server.
>
> Note: `$env:NAME = "value"` is the **PowerShell** way to set an environment
> variable. `set NAME=value` is cmd.exe syntax and won't work here.

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
[PASS] login teacher (200, role=teacher)
[PASS] create trivia set (200)
[PASS] get_analytics (200, 2 empty entries)
[PASS] register student (201)
[PASS] login student (200, role=student)
[PASS] get question 0 (200)
[PASS] no answer key leaked
[PASS] verify answer q0 correct
[PASS] advance to question 1 (200)
[PASS] verify answer q1 correct
[PASS] reach end of quiz gracefully (200, done=true)

ALL PASSED
```

## Running it again

The manager keeps everything (users, trivia sets) **in memory only**. If you
run the smoke test twice without restarting Terminals 1 and 2, it'll fail on
registration with "username already taken" because `ms_smith`/`bobby`
already exist.

To re-test cleanly:
1. `Ctrl+C` in Terminal 1 and Terminal 2
2. Re-run the commands from steps 2 and 3
3. Re-run the smoke test in Terminal 3

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'server'` | Not in the right folder | `cd` into the folder that actually contains `server.py` (check with `Get-ChildItem`) |
| `[security.py] WARNING: TRIVIA_HMAC_SECRET not set...` | Env var not set in that terminal, or set with wrong syntax | Use `$env:TRIVIA_HMAC_SECRET = "Jordan"` (not `set ...=...`) — and set it in *every* terminal |
| `ConnectionRefusedError` / `URLError` when running `smoke_test.py` | `server.py` (or `trivia-manager.py`) isn't actually running yet | Check Terminals 1 and 2 are still open and showing they're running, not back at a prompt |
| `Could not connect to the trivia-manager backend...` from `server.py` | Terminal 1 wasn't started first, or crashed | Start Terminal 1 before Terminal 2; check Terminal 1 for errors |
| `invalid or missing payload signature` | `TRIVIA_HMAC_SECRET` differs between terminals | Make sure all three terminals used the exact same secret string |
| `"username already taken"` failures | Re-running without restarting the backend | See "Running it again" above |
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
