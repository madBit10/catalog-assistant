from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,               # test pooled connections before use
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,                  # write to the DB only when we say so
    expire_on_commit=False,           # objects stay readable after commit
)

def get_db():                         # FastAPI dependency (API routes only)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()