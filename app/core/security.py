import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain_password: str):
    """Return a salted bcrypt hash to store in the database"""
    # Generate a salt and hash the password
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
    # Store as a string in the database
    return hashed_bytes.decode('utf-8')

def check_password(plain_password: str, password_hash: str) -> bool:
    """Check a login attempt against the stored hash."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        password_hash.encode('utf-8')
    )


# A real bcrypt hash of a random password. Login checks against it when the
# email doesn't exist, so "unknown email" takes as long as "wrong password"
# and response time can't reveal which emails have accounts.
DUMMY_PASSWORD_HASH = hash_password(uuid.uuid4().hex)


def create_access_token(user_id: uuid.UUID) -> str:
    """Signed JWT holding the user's id (sub) and an expiry (exp)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    """User id from a valid token; None if expired, tampered or malformed."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            # Pin the algorithm: never trust the one named in the token header
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None
