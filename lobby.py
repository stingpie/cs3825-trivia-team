"""
lobby.py
Darren Robinson -- Networking & Real-Time Sync Lead

Game-room lobby helpers used by trivia-manager.py:
  - 4-digit room PIN generation (matches the frontend Join Room UI)
  - room record construction
  - player roster snapshots safe to send over the wire

Shared mutable lobby state lives in trivia-manager.py (the process every
host talks to). This module stays dependency-light so it can be unit-
tested without Flask or the multiprocessing manager.
"""

import random
import time


def generate_room_code(existing_codes) -> str:
    """
    Allocate a 4-digit PIN that is not already in use.
    Format matches the frontend maxlength=4 room input (e.g. "4821").
    """
    existing = set(existing_codes)
    for _ in range(100):
        code = f"{random.randint(0, 9999):04d}"
        if code not in existing:
            return code
    raise RuntimeError("could not allocate a free room code")


def make_room(host_uuid: str, idx_of_trivia_set: int, pacing_mode: str = "self") -> dict:
    """
    Build a new lobby record.

    status:
      waiting  -- players may join; quiz not started
      active   -- host started the game; players may fetch questions
      ended    -- session closed
    """
    if pacing_mode not in ("self", "host"):
        pacing_mode = "self"
    return {
        "host_uuid": host_uuid,
        "idx_of_trivia_set": int(idx_of_trivia_set),
        "pacing_mode": pacing_mode,
        "status": "waiting",
        "locked": False,
        "players": {},  # uuid -> {username, role, joined_at}
        "created_at": time.time(),
        "question_idx": 0,  # shared index for host-paced mode
    }


def public_room_view(room_code: str, room: dict) -> dict:
    """Strip nothing sensitive -- rooms hold no passwords -- but shape a
    stable JSON response for clients."""
    players = [
        {
            "UUID": uuid,
            "username": info.get("username"),
            "role": info.get("role"),
        }
        for uuid, info in room.get("players", {}).items()
    ]
    return {
        "room_code": room_code,
        "host_uuid": room["host_uuid"],
        "idx_of_trivia_set": room["idx_of_trivia_set"],
        "pacing_mode": room["pacing_mode"],
        "status": room["status"],
        "locked": room["locked"],
        "player_count": len(players),
        "players": players,
        "question_idx": room.get("question_idx", 0),
    }
