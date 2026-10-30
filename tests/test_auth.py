"""Real-user scenarios for accounts and login (SYSTEM_DESIGN.md §6)."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from tests.conftest import register_and_login


def test_new_user_can_register_and_password_is_never_returned(client):
    r = client.post("/auth/register", json={"email": "shop@example.com", "password": "correct-horse-1"})
    assert r.status_code == 201
    assert r.json()["email"] == "shop@example.com"
    assert "password" not in r.text and "password_hash" not in r.text


def test_same_email_with_different_capitals_cannot_register_twice(client):
    client.post("/auth/register", json={"email": "shop@example.com", "password": "correct-horse-1"})
    r = client.post("/auth/register", json={"email": "  Shop@Example.COM ", "password": "correct-horse-2"})
    assert r.status_code == 409


def test_user_can_log_in_with_different_capitals_in_email(client):
    client.post("/auth/register", json={"email": "shop@example.com", "password": "correct-horse-1"})
    r = client.post("/auth/login", data={"username": "SHOP@example.com", "password": "correct-horse-1"})
    assert r.status_code == 200


def test_invalid_email_is_rejected(client):
    r = client.post("/auth/register", json={"email": "not-an-email", "password": "correct-horse-1"})
    assert r.status_code == 422


def test_short_password_is_rejected(client):
    r = client.post("/auth/register", json={"email": "shop@example.com", "password": "short"})
    assert r.status_code == 422


def test_overlong_password_is_rejected_cleanly(client):
    # 37 characters but 74 bytes: a password manager passphrase with accents.
    # Must be a clear 422, not a 500 from bcrypt.
    r = client.post("/auth/register", json={"email": "shop@example.com", "password": "é" * 37})
    assert r.status_code == 422
    assert "too long" in r.text


def test_wrong_password_gives_generic_error(client):
    client.post("/auth/register", json={"email": "shop@example.com", "password": "correct-horse-1"})
    wrong_password = client.post("/auth/login", data={"username": "shop@example.com", "password": "wrong-pass-1"})
    unknown_email = client.post("/auth/login", data={"username": "nobody@example.com", "password": "wrong-pass-1"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same message, so an attacker can't learn which emails have accounts
    assert wrong_password.json() == unknown_email.json()


def test_logged_in_user_can_see_their_account(client):
    headers = register_and_login(client)
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "shop@example.com"


def test_request_without_token_is_rejected(client):
    assert client.get("/auth/me").status_code == 401


def test_expired_token_is_rejected(client):
    # The tab left open overnight
    user_id = client.get("/auth/me", headers=register_and_login(client)).json()["id"]
    expired = jwt.encode(
        {"sub": user_id, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_forged_token_is_rejected(client):
    # Signed with someone else's secret
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker-secret-" + "y" * 32,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_of_deleted_account_stops_working(client, db):
    from app.db.models import User

    headers = register_and_login(client)
    db.query(User).delete()
    db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401
