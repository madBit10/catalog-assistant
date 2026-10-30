import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        # "Shop@X.com" and "shop@x.com" are the same account
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def password_length_in_bytes(cls, value: str) -> str:
        # bcrypt only accepts 72 BYTES (5.x raises above that). Count bytes,
        # not characters: "é" is 1 character but 2 bytes.
        size = len(value.encode("utf-8"))
        if size < 8:
            raise ValueError("Password must be at least 8 characters.")
        if size > 72:
            raise ValueError("Password is too long (maximum 72 bytes). Please choose a shorter one.")
        return value


class UserOut(BaseModel):
    # Never includes password_hash
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
