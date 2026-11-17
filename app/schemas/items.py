# Concept: an UPDATE schema. Every field is optional; only the fields the
# user actually sends are changed (a "partial update", HTTP PATCH).
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ItemUpdate(BaseModel):
    """Why: the review screen lets the user fix what the AI wrote.
    Example: PATCH /items/{id}  {"title": "Mindset Is Everything Tee"}
      -> only title changes; "title" is added to edited_fields, so the AI never overwrites it
    Unknown fields (e.g. "status", "stored_path") are REJECTED, not ignored."""
    # Concept: extra="forbid" stops users from editing fields they shouldn't (mass assignment)
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: Literal["women", "men", "kids", "baby"] | None = None
    colours: list[str] | None = Field(default=None, max_length=10)
    tags: list[str] | None = Field(default=None, max_length=20)
