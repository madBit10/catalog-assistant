import os

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# --- Make tests use a separate database: catalog_test, not catalog ---
# This must run BEFORE any `app` import: app/db/database.py builds its
# engine the moment it's imported, using whatever DATABASE_URL is set then.

# Read the real URL from .env, e.g. postgresql+psycopg2://user:pw@localhost:5432/catalog
_real_url = make_url(dotenv_values(".env")["DATABASE_URL"])
# Same server and login, only the database name changes: .../catalog_test
_test_url = _real_url.set(database=f"{_real_url.database}_test")
# pydantic-settings reads environment variables BEFORE .env, so setting it
# here makes the whole app (settings → engine) use the test database
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
# A fake signing secret just for tests (32+ chars so config accepts it);
# tests never need or see your real JWT_SECRET
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32

# `# noqa: E402` tells the linter "yes, these imports are below code on
# purpose" (they must come after the environment variables above).
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
# Importing models registers the 3 tables on Base.metadata, so create_all()
# below knows what to build. "as _models" matters: a plain `import app.db.models`
# would overwrite the name `app` (the FastAPI app above) with the app PACKAGE,
# and every TestClient(app) would crash. F401 = "imported but unused" is fine.
import app.db.models as _models  # noqa: E402,F401


def _create_test_database_if_missing():
    admin = create_engine(_real_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _test_url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database():
    _create_test_database_if_missing()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables():
    # Every test starts with empty tables
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE users, batches, items CASCADE"))


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def register_and_login(client, email="shop@example.com", password="correct-horse-1"):
    """Helper: create an account and return the auth header for it."""
    client.post("/auth/register", json={"email": email, "password": password})
    token = client.post("/auth/login", data={"username": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
