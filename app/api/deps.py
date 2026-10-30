from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import User

# Reads "Authorization: Bearer <token>"; tokenUrl powers the Authorize button in /docs
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """The logged-in user, or 401. Every protected route depends on this."""
    user_id = decode_access_token(token)
    if user_id is None:
        raise CREDENTIALS_ERROR
    # A valid token for a deleted account must not work
    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_ERROR
    return user
