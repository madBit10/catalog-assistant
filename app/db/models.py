import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class ItemStatus(str, enum.Enum):
    # The item lifecycle from SYSTEM_DESIGN.md §3. The DB rejects any other value.
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ItemCategory(str, enum.Enum):
    # The only categories Claude is allowed to return.
    WOMEN = "women"
    MEN = "men"
    KIDS = "kids"
    BABY = "baby"


def _enum_values(enum_cls):
    # Store the lowercase values ("queued"), not the Python names ("QUEUED").
    return [member.value for member in enum_cls]


class User(Base):
    __tablename__ = "users"

    # Generates a random UUID on the Python side before inserting into the DB
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    # email to lowercase (see validate_email); unique so one account per email
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True
    )
    # Secure password hash column stores secured hash string and not the plain string
    password_hash: Mapped[str] = mapped_column(
        String(60)
    )
    # record keeping the user creation
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    @validates('email')
    def validate_email(self, key, address):
        if address:
            return address.strip().lower()
        return address


class Batch(Base):
    __tablename__ = "batches"

    # Generates a random UUID on the Python side before inserting into the DB
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    # The owner. CASCADE: deleting a user deletes their batches (and, through
    # items.batch_id, their items). Files in storage/ must be deleted by code.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    # Sent by the browser with each upload; a double-click reuses the same key,
    # so the second request returns the existing batch instead of a new one
    idempotency_key: Mapped[str] = mapped_column(
        String(64)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        # Unique per user, not globally: two users may send the same key
        UniqueConstraint("user_id", "idempotency_key", name="uq_batches_user_idempotency_key"),
        # "My batches, newest first" and the daily upload quota
        Index("ix_batches_user_created", "user_id", "created_at"),
    )


class Item(Base):
    # One row per uploaded photo
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    # No user_id here: the owner is reached through the batch (Decision Q2).
    # Indexed because progress counts and ownership checks both filter on it.
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        index=True
    )

    # --- Files ---
    # What the user called the file. Display only, never used as a path.
    original_filename: Mapped[str] = mapped_column(String(255))
    # Random file names we generate; clean_path is empty until the worker runs
    stored_path: Mapped[str] = mapped_column(String(255))
    clean_path: Mapped[str | None] = mapped_column(String(255))

    # --- Processing state ---
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, name="item_status", values_callable=_enum_values),
        default=ItemStatus.QUEUED,
        server_default=ItemStatus.QUEUED.value
    )
    # Retry policy counts these; last_error is shown to the user on failure
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)

    # --- AI output (all empty until Claude has run) ---
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[ItemCategory | None] = mapped_column(
        Enum(ItemCategory, name="item_category", values_callable=_enum_values)
    )
    # PostgreSQL arrays; empty list instead of NULL so code never checks for None
    colours: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        server_default=text("'{}'")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        server_default=text("'{}'")
    )
    # Claude's answer to "is this actually clothing?"; False -> needs_review
    is_product: Mapped[bool | None]

    # Fields the human edited; the worker never overwrites these (Decision Q3)
    edited_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        server_default=text("'{}'")
    )

    # --- Cost tracking (Haiku vs Opus comparison) ---
    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    # onupdate: SQLAlchemy sets it to now() on every UPDATE it sends
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
