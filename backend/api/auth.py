"""Signup, login and logout. The session lives in a cookie that page scripts cannot read."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Annotated

import certifi
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from pymongo import MongoClient

from keel.llm import read_env_file
from keel.users import SESSION_DAYS, EmailTaken, UserStore

COOKIE = "keel_session"
DEFAULT_URI = "mongodb://localhost:27017"
DATABASE = "keel"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254
MAX_NAME = 120
MIN_PASSWORD = 8
MAX_PASSWORD = 128  # Hashing cost should not be something a request can inflate.

router = APIRouter(prefix="/api/auth")


def tls_options(uri: str) -> dict:
    """Python on a Mac may trust no certificates, so a cloud database needs certifi's list."""
    return {"tlsCAFile": certifi.where()} if uri.startswith("mongodb+srv://") else {}


@lru_cache(maxsize=1)
def get_users() -> UserStore:
    uri = {**read_env_file(), **os.environ}.get("MONGODB_URI", DEFAULT_URI)
    # Fail quickly with a clear message when the database is down, not after 30 s.
    client = MongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True, **tls_options(uri))
    store = UserStore(client[DATABASE])
    store.ensure_indexes()
    return store


Users = Annotated[UserStore, Depends(get_users)]
SessionCookie = Annotated[str | None, Cookie(alias=COOKIE)]


class Signup(BaseModel):
    name: str
    email: str
    password: str


class Login(BaseModel):
    email: str
    password: str


def _public(user: dict | None) -> dict:
    if user is None:
        return {"user": None}
    return {"user": {"id": str(user["_id"]), "name": user["name"], "email": user["email"]}}


def _set_cookie(request: Request, response: Response, token: str) -> None:
    # Behind OpenShift's route the app itself sees http, so the proxy's header decides.
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=https,
        path="/",
    )


@router.post("/signup", status_code=201)
def signup(entry: Signup, request: Request, response: Response, users: Users) -> dict:
    name = entry.name.strip()
    email = entry.email.strip()
    if not name or len(name) > MAX_NAME:
        raise HTTPException(422, f"Enter a name of up to {MAX_NAME} characters.")
    if len(email) > MAX_EMAIL or not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if not MIN_PASSWORD <= len(entry.password) <= MAX_PASSWORD:
        raise HTTPException(422, f"Use a password of {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
    try:
        user = users.create_user(name, email, entry.password)
    except EmailTaken as error:
        raise HTTPException(409, "An account with this email already exists.") from error
    _set_cookie(request, response, users.start_session(user))
    return _public(user)


@router.post("/login")
def login(entry: Login, request: Request, response: Response, users: Users) -> dict:
    user = None
    if len(entry.password) <= MAX_PASSWORD:
        user = users.check_login(entry.email, entry.password)
    if user is None:
        # The same answer either way, so this cannot be used to find out who has an account.
        raise HTTPException(401, "Wrong email or password.")
    _set_cookie(request, response, users.start_session(user))
    return _public(user)


@router.post("/logout")
def logout(response: Response, users: Users, token: SessionCookie = None) -> dict:
    if token:
        users.end_session(token)
    response.delete_cookie(COOKIE, path="/")
    return _public(None)


@router.get("/session")
def session(users: Users, token: SessionCookie = None) -> dict:
    """Who is logged in. Being logged out is a normal answer, not an error."""
    return _public(users.user_for_token(token) if token else None)
