# Educational Trivia Platform (COMP 3825)

MUST Install Flask and bcrypt for security code to work:

```
py -m pip install flask bcrypt
```

## Running it

```
python3 trivia-manager.py          # terminal 1
python3 -m flask --app server run  # terminal 2
```
See [TESTING_GUIDE.md](TESTING_GUIDE.md) for the full walkthrough, including
running [smoke_test.py](smoke_test.py) to verify the whole flow end-to-end.

## Docs

- [PROTOCOL.md](PROTOCOL.md) — custom JSON application protocol (Darren Robinson)
- [protocol_spec.json](protocol_spec.json) — machine-readable message catalog
- [lobby.py](lobby.py) — game room PIN / lobby helpers (Darren Robinson)
- [TESTING_GUIDE.md](TESTING_GUIDE.md) — local smoke-test walkthrough
- [smoke_test.py](smoke_test.py) — end-to-end test script the guide above walks through
