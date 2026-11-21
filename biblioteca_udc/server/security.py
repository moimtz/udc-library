"""Passwords, sessions and permission checks."""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException

import config
from db import get_conn, now

ITERATIONS = 400_000
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(test.hex(), digest)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=config.SESSION_DAYS)
    conn.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                 (_token_hash(token), user_id, now(), expires.isoformat(timespec="seconds")))
    conn.commit()
    return token


def end_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    conn.commit()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not signed in.")
    return authorization[7:].strip()


def current_user(authorization: str | None = Header(None), conn=Depends(get_conn)):
    token = _bearer(authorization)
    row = conn.execute(
        "SELECT u.id, u.username, u.role, u.disabled, s.expires_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (_token_hash(token),)).fetchone()
    if not row or row["disabled"] or row["expires_at"] < now():
        raise HTTPException(401, "Session expired. Sign in again.")
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def require_editor(user=Depends(current_user)):
    if ROLE_RANK[user["role"]] < ROLE_RANK["editor"]:
        raise HTTPException(403, "Your account is read-only.")
    return user


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Only the administrator can do this.")
    return user


# --- very small brute-force guard (in memory) ------------------------------
_FAILS: dict[tuple[str, str], list[float]] = {}


def check_login_allowed(ip: str, username: str) -> None:
    window = [t for t in _FAILS.get((ip, username.lower()), []) if time.time() - t < 300]
    _FAILS[(ip, username.lower())] = window
    if len(window) >= 5:
        raise HTTPException(429, "Too many failed attempts. Wait 5 minutes and try again.")


def register_failure(ip: str, username: str) -> None:
    _FAILS.setdefault((ip, username.lower()), []).append(time.time())


def clear_failures(ip: str, username: str) -> None:
    _FAILS.pop((ip, username.lower()), None)
