"""User accounts and login sessions, stored in MongoDB.

Passwords are stored only as Argon2 hashes. Session tokens are stored only as SHA-256 hashes,
so reading the database gives nobody a working password or a working login.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pymongo.errors import DuplicateKeyError

SESSION_DAYS = 14

_hasher = PasswordHasher()
# Checked when an email is unknown, so a login takes as long whether or not the account exists.
_NO_ACCOUNT_HASH = _hasher.hash(secrets.token_urlsafe(16))


class EmailTaken(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _password_matches(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


class UserStore:
    def __init__(self, database) -> None:
        self.users = database["users"]
        self.sessions = database["sessions"]

    def ensure_indexes(self) -> None:
        self.users.create_index("email", unique=True)
        self.sessions.create_index("token_hash", unique=True)
        # MongoDB deletes a session by itself once expires_at has passed.
        self.sessions.create_index("expires_at", expireAfterSeconds=0)

    def create_user(self, name: str, email: str, password: str) -> dict:
        user = {
            "name": name.strip(),
            "email": normalize_email(email),
            "password_hash": _hasher.hash(password),
            "created_at": datetime.now(timezone.utc),
        }
        try:
            self.users.insert_one(user)
        except DuplicateKeyError as error:
            raise EmailTaken from error
        return user

    def check_login(self, email: str, password: str) -> dict | None:
        user = self.users.find_one({"email": normalize_email(email)})
        matches = _password_matches(user["password_hash"] if user else _NO_ACCOUNT_HASH, password)
        return user if user and matches else None

    def start_session(self, user: dict) -> str:
        """Returns the token for the browser's cookie. Only its hash is kept."""
        token = secrets.token_urlsafe(32)
        self.sessions.insert_one(
            {
                "token_hash": _token_hash(token),
                "user_id": user["_id"],
                "expires_at": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
            }
        )
        return token

    def user_for_token(self, token: str) -> dict | None:
        # MongoDB's clean-up of expired sessions can lag, so the date is checked here too.
        session = self.sessions.find_one(
            {"token_hash": _token_hash(token), "expires_at": {"$gt": datetime.now(timezone.utc)}}
        )
        return self.users.find_one({"_id": session["user_id"]}) if session else None

    def end_session(self, token: str) -> None:
        self.sessions.delete_one({"token_hash": _token_hash(token)})
