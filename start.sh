#!/usr/bin/env bash
# Render only runs one start command per service, but this app is two
# processes (trivia-manager.py + server.py) that talk to each other over
# localhost:5555. This script starts both inside the same container so
# that connection actually works.
set -e

# Start the backend manager in the background.
python3 trivia-manager.py &
MANAGER_PID=$!

# Give it a moment to bind to port 5555 before server.py tries to connect.
# (server.py also has its own retry logic, but this avoids relying on it.)
sleep 2

# If the manager already died (e.g. missing dependency, bad code), fail
# loudly now instead of letting server.py hang on a connection that will
# never succeed.
if ! kill -0 "$MANAGER_PID" 2>/dev/null; then
    echo "trivia-manager.py exited immediately -- check the log above for its error."
    exit 1
fi

# Start the web server in the foreground, bound to Render's assigned port.
# --host 0.0.0.0 is required: Render's health checks come from outside the
# container, so binding to 127.0.0.1 (the default) would be unreachable.
# --with-threads is required once more than one browser is actually
# connected: this app's frontend polls several endpoints (heartbeat every
# 5s, room standings every 3s, waiting-room status every 2s) from EVERY
# connected client. Flask's dev server handles one request at a time
# without this flag, so with 2-3+ browsers polling concurrently, requests
# queue up behind each other -- most visibly, a host's heartbeat PING can
# sit in the queue long enough to miss reliability.py's 15s connectivity
# window, showing the host as "Offline" even though their tab is open and
# fine. Threading fixes that by letting the dev server handle requests
# concurrently instead of serially.
exec python3 -m flask --app server run --host 0.0.0.0 --port "$PORT" --with-threads
