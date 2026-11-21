"""Login and user administration."""
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

import security
from db import get_conn, now

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(BaseModel):
    password: str | None = None
    role: str | None = None
    disabled: bool | None = None


def _check_password(pw: str) -> None:
    if len(pw) < 8:
        raise HTTPException(422, "Password must have at least 8 characters.")


@router.post("/auth/login")
def login(body: LoginIn, request: Request, conn=Depends(get_conn)):
    ip = request.client.host if request.client else "?"
    security.check_login_allowed(ip, body.username)
    row = conn.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    if not row or row["disabled"] or not security.verify_password(body.password, row["pw_hash"]):
        security.register_failure(ip, body.username)
        raise HTTPException(401, "Wrong username or password.")
    security.clear_failures(ip, body.username)
    token = security.create_session(conn, row["id"])
    return {"token": token, "user": {"id": row["id"], "username": row["username"], "role": row["role"]}}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(None), user=Depends(security.current_user), conn=Depends(get_conn)):
    security.end_session(conn, authorization[7:].strip())
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(security.current_user)):
    return user


@router.get("/users")
def list_users(admin=Depends(security.require_admin), conn=Depends(get_conn)):
    rows = conn.execute("SELECT id, username, role, disabled, created_at FROM users ORDER BY username").fetchall()
    return [dict(r) | {"disabled": bool(r["disabled"])} for r in rows]


@router.post("/users", status_code=201)
def create_user(body: UserIn, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", body.username):
        raise HTTPException(422, "Username: 3-32 characters, letters, digits, dot, dash or underscore.")
    if body.role not in security.ROLE_RANK:
        raise HTTPException(422, "Role must be admin, editor or viewer.")
    _check_password(body.password)
    if conn.execute("SELECT 1 FROM users WHERE username=?", (body.username,)).fetchone():
        raise HTTPException(409, "That username already exists.")
    cur = conn.execute("INSERT INTO users(username,pw_hash,role,created_at) VALUES (?,?,?,?)",
                       (body.username, security.hash_password(body.password), body.role, now()))
    conn.commit()
    return {"id": cur.lastrowid}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "User not found.")
    if user_id == admin["id"] and (body.disabled or (body.role and body.role != "admin")):
        raise HTTPException(422, "You cannot disable or demote your own account.")
    if body.password is not None:
        _check_password(body.password)
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (security.hash_password(body.password), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    if body.role is not None:
        if body.role not in security.ROLE_RANK:
            raise HTTPException(422, "Role must be admin, editor or viewer.")
        conn.execute("UPDATE users SET role=? WHERE id=?", (body.role, user_id))
    if body.disabled is not None:
        conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(body.disabled), user_id))
        if body.disabled:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    if user_id == admin["id"]:
        raise HTTPException(422, "You cannot delete your own account.")
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    return {"ok": True}
