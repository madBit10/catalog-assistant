from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Pydantic v2 style (replaces the v1 inner `class Config`).
    # env_file: read values from .env in the project root.
    # extra="ignore": .env also holds POSTGRES_* keys for docker-compose;
    # without this, unknown keys would stop the app from starting.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    # Signs every login token. An empty or short secret lets anyone forge a
    # token, so the app refuses to start without 32+ characters.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

settings = Settings()
