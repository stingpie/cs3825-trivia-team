"""
reliability.py
Jordan Steele -- Security & QA Lead

Implements the server-side half of the reliability plan:
  - Heartbeat (PING/PONG) tracking, so dropped clients can be detected
  - Reconnection token bookkeeping, so a client that drops Wi-Fi can
    resume its session without losing game progress
  - a small failure-scenario test harness (invalid input, bad
    credentials, dropped connections) with latency measurement

This Code is deliberately dependency-light (stdlib only) so it can
run standalone for testing, or be imported into server.py.
"""

import time
import threading
import statistics



# Heartbeat tracking (server side of PING/PONG, protocol_spec.json §6.3)

HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_TIMEOUT_SECONDS = 15  # 3 missed beats = considered disconnected

_last_seen_lock = threading.Lock()
_last_seen = {}  # UUID -> unix timestamp of last PING received


def record_heartbeat(uuid: str) -> dict:
    """
    Call this whenever a PING message arrives from a client.
    Returns the PONG payload to send back.
    """
    now = time.time()
    with _last_seen_lock:
        _last_seen[uuid] = now
    return {"type": "PONG", "timestamp": int(now)}


def is_connected(uuid: str) -> bool:
    """True if we've heard a heartbeat from this user within the timeout window."""
    with _last_seen_lock:
        last = _last_seen.get(uuid)
    if last is None:
        return False
    return (time.time() - last) <= HEARTBEAT_TIMEOUT_SECONDS


def get_disconnected_users() -> list:
    """Returns UUIDs that have missed their heartbeat window (for cleanup/alerts)."""
    now = time.time()
    with _last_seen_lock:
        return [
            uuid for uuid, last in _last_seen.items()
            if (now - last) > HEARTBEAT_TIMEOUT_SECONDS
        ]

# Reconnection support

_reconnect_lock = threading.Lock()
_reconnect_state = {}  # UUID -> {'idx_of_trivia_set':..., 'question_idx':..., 'room_code':...}


def save_reconnect_state(uuid: str, idx_of_trivia_set: int, question_idx: int, room_code: str = None):
    """
    Snapshot enough state that a dropped client can rejoin exactly where
    they left off. Call this after every answer submission, not just on
    disconnect, since disconnects aren't always detected cleanly.
    """
    with _reconnect_lock:
        _reconnect_state[uuid] = {
            "idx_of_trivia_set": idx_of_trivia_set,
            "question_idx": question_idx,
            "room_code": room_code,
            "saved_at": time.time(),
        }


def load_reconnect_state(uuid: str):
    """Returns the last saved state dict for a UUID, or None if there isn't one."""
    with _reconnect_lock:
        return _reconnect_state.get(uuid)


def clear_reconnect_state(uuid: str):
    with _reconnect_lock:
        _reconnect_state.pop(uuid, None)

# J4: Failure scenario testing suite & latency metrics

class TestResult:
    def __init__(self, name, passed, latency_ms, detail=""):
        self.name = name
        self.passed = passed
        self.latency_ms = latency_ms
        self.detail = detail

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} ({self.latency_ms:.1f} ms) {self.detail}"


def _timed(name, fn):
    start = time.perf_counter()
    try:
        ok, detail = fn()
    except Exception as exc:  # a raised exception during a failure test is itself a failure
        ok, detail = False, f"unhandled exception: {exc!r}"
    elapsed_ms = (time.perf_counter() - start) * 1000
    return TestResult(name, ok, elapsed_ms, detail)


def run_failure_suite(client_call):
    scenarios = [
        "invalid_json_body",
        "missing_required_field",
        "wrong_password",
        "expired_session_token",
        "tampered_hmac_signature",
        "student_hits_teacher_only_route",
        "dropped_connection_mid_submit",
    ]

    results = [_timed(name, lambda n=name: client_call(n)) for name in scenarios]

    latencies = [r.latency_ms for r in results]
    summary = {
        "results": results,
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
    }
    return summary


if __name__ == "__main__":
    # Minimal smoke test using a fake client_call, so this file can be run
    # directly (`python reliability.py`) to sanity-check the harness itself
    def fake_client_call(scenario_name):
        # Pretend every scenario is handled correctly except one, to show
        # what a failing report line looks like.
        if scenario_name == "tampered_hmac_signature":
            return False, "server accepted a tampered payload -- BUG"
        return True, "handled as expected"

    report = run_failure_suite(fake_client_call)
    for r in report["results"]:
        print(r)
    print(f"\n{report['passed']} passed, {report['failed']} failed, "
          f"avg latency {report['avg_latency_ms']:.1f} ms, "
          f"max latency {report['max_latency_ms']:.1f} ms")
