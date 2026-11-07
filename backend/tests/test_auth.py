"""Accounts against an in-memory stand-in for MongoDB."""
from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

import api.main as api
from api.auth import COOKIE, get_users, tls_options
from keel.users import UserStore

ACCOUNT = {"name": "Ada", "email": "Ada@Example.com", "password": "correct horse"}


@pytest.fixture
def store():
    store = UserStore(mongomock.MongoClient(tz_aware=True)["keel"])
    store.ensure_indexes()
    return store


@pytest.fixture
def client(store):
    api.app.dependency_overrides[get_users] = lambda: store
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def logged_in_user(client):
    return client.get("/api/auth/session").json()["user"]


def test_signup_logs_in_and_never_returns_the_password(client):
    response = client.post("/api/auth/signup", json=ACCOUNT)
    assert response.status_code == 201
    user = response.json()["user"]
    assert set(user) == {"id", "name", "email"}
    assert user["email"] == "ada@example.com"
    assert logged_in_user(client)["name"] == "Ada"


def test_the_database_holds_no_password_or_token_in_plain_text(client, store):
    client.post("/api/auth/signup", json=ACCOUNT)
    stored = store.users.find_one({"email": "ada@example.com"})
    assert ACCOUNT["password"] not in str(stored)
    assert stored["password_hash"].startswith("$argon2")
    token = client.cookies[COOKIE]
    assert token not in str(store.sessions.find_one({}))


def test_the_session_cookie_is_hidden_from_page_scripts(client):
    cookie = client.post("/api/auth/signup", json=ACCOUNT).headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie


def test_the_cookie_is_https_only_behind_an_https_proxy(client):
    response = client.post("/api/auth/signup", json=ACCOUNT, headers={"x-forwarded-proto": "https"})
    assert "secure" in response.headers["set-cookie"].lower()


def test_an_email_can_only_be_used_once_whatever_its_case(client):
    client.post("/api/auth/signup", json=ACCOUNT)
    again = client.post("/api/auth/signup", json={**ACCOUNT, "email": "ada@EXAMPLE.com"})
    assert again.status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"name": "  "},
        {"email": "not-an-email"},
        {"password": "short"},
        {"password": "x" * 129},
    ],
)
def test_signup_refuses_bad_details_with_a_readable_message(client, store, change):
    response = client.post("/api/auth/signup", json={**ACCOUNT, **change})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert store.users.count_documents({}) == 0


def test_login_with_the_right_password(client):
    client.post("/api/auth/signup", json=ACCOUNT)
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email": "ada@example.com", "password": ACCOUNT["password"]})
    assert response.status_code == 200
    assert logged_in_user(client)["email"] == "ada@example.com"


@pytest.mark.parametrize(
    "attempt",
    [
        {"email": "ada@example.com", "password": "wrong password"},
        {"email": "nobody@example.com", "password": "correct horse"},
        {"email": "ada@example.com", "password": "x" * 5000},
    ],
)
def test_a_failed_login_says_the_same_thing_and_logs_nobody_in(client, attempt):
    client.post("/api/auth/signup", json=ACCOUNT)
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json=attempt)
    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong email or password."
    assert logged_in_user(client) is None


def test_a_query_object_cannot_stand_in_for_an_email(client):
    client.post("/api/auth/signup", json=ACCOUNT)
    response = client.post("/api/auth/login", json={"email": {"$ne": ""}, "password": ACCOUNT["password"]})
    assert response.status_code == 422


def test_logout_ends_the_session_on_the_server_too(client, store):
    client.post("/api/auth/signup", json=ACCOUNT)
    token = client.cookies[COOKIE]
    client.post("/api/auth/logout")
    assert store.sessions.count_documents({}) == 0
    assert store.user_for_token(token) is None


def test_an_expired_or_made_up_session_is_not_logged_in(client, store):
    client.post("/api/auth/signup", json=ACCOUNT)
    token = client.cookies[COOKIE]
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    store.sessions.update_many({}, {"$set": {"expires_at": past}})
    assert store.user_for_token(token) is None
    assert store.user_for_token("made-up") is None


def test_only_a_cloud_database_gets_a_certificate_list():
    assert "tlsCAFile" in tls_options("mongodb+srv://cluster.example.net")
    assert tls_options("mongodb://localhost:27017") == {}


def test_a_database_that_is_down_gives_a_clear_message():
    def unreachable():
        raise ServerSelectionTimeoutError("no server")

    api.app.dependency_overrides[get_users] = unreachable
    try:
        response = TestClient(api.app).get("/api/auth/session")
    finally:
        api.app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "database" in response.json()["detail"]
