# Concept: SCHEMA = the shape of the JSON the API returns.
# Only fields listed here leave the server, so internal columns stay hidden.
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ItemCategory, ItemStatus


class ItemOut(BaseModel):
    # Concept: from_attributes lets Pydantic read a SQLAlchemy object (item.title)
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    status: ItemStatus
    last_error: str | None
    title: str | None
    description: str | None
    category: ItemCategory | None
    colours: list[str]
    tags: list[str]
    is_product: bool | None
    edited_fields: list[str]
    created_at: datetime
    updated_at: datetime
    # Left out on purpose: stored_path/clean_path (server disk paths),
    # model/tokens (internal cost data)


class Progress(BaseModel):
    # Computed by counting items, never stored (Decision Q1)
    total: int = 0
    queued: int = 0
    processing: int = 0
    done: int = 0
    needs_review: int = 0
    failed: int = 0


class RejectedFile(BaseModel):
    # A file that failed validate_image(). Not saved, so no item row.
    filename: str
    reason: str


class BatchSummary(BaseModel):
    # For the "my batches" list: no items, so it stays small
    id: uuid.UUID
    created_at: datetime
    progress: Progress


class BatchOut(BatchSummary):
    # Concept: INHERITANCE. BatchOut = BatchSummary + items + rejected
    items: list[ItemOut]
    rejected: list[RejectedFile] = []
