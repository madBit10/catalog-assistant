import logging
import uuid
from typing import Literal

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import Item, ItemCategory, ItemStatus, User
from app.schemas.batches import ItemOut
from app.schemas.items import ItemUpdate
from app.services.ownership import get_item_for_user
from app.services.queue import JobQueue, get_queue
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["items"])
BUSY = (ItemStatus.QUEUED, ItemStatus.PROCESSING)


def _item_or_404(db: Session, item_id: uuid.UUID, user: User) -> Item:
    """Why: every item route needs "load it, and 404 if it's missing or not yours".
    Example: Bob passes Alice's item id -> 404 "Item not found." (same as a made-up id)"""
    item = get_item_for_user(db, item_id, user)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found.")
    return item


def _clean_list(values: list[str]) -> list[str]:
    """Why: user input gets the same tidy-up as AI output.
    Example: [" Navy", "navy", ""] -> ["navy"]"""
    out = []
    for v in values:
        v = v.strip().lower()
        if v and v not in out:
            out.append(v)
    return out


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(item_id: uuid.UUID, body: ItemUpdate,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Why: the user fixes what the AI wrote. Edited fields are protected forever (Decision Q3).

    Examples:
      {"title": "Mindset Is Everything Tee"}   -> 200, edited_fields = ["title"]
      {}                                       -> 422 "Nothing to update."
      {"status": "done"}                       -> 422 (field not allowed)
      while the photo is still processing      -> 409 "wait a few seconds"
    """
    item = _item_or_404(db, item_id, user)
    # Concept: LOST UPDATE. If the worker is mid-way, it would write the AI answer
    # over this edit seconds later. Simplest safe rule: no edits while busy.
    if item.status in BUSY:
        raise HTTPException(status.HTTP_409_CONFLICT, "This photo is still being processed. Please wait a few seconds.")

    changes = body.model_dump(exclude_unset=True)   # only what the user actually sent
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to update.")
    for field, value in changes.items():
        if field == "category" and value is not None:
            value = ItemCategory(value)
        elif field in ("colours", "tags") and value is not None:
            value = _clean_list(value)
        setattr(item, field, value)

    # Concept: assign a NEW list. SQLAlchemy doesn't notice in-place .append()
    # on an ARRAY column, so the change would silently never be saved.
    item.edited_fields = sorted(set(item.edited_fields) | set(changes))
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/retry", response_model=ItemOut, status_code=status.HTTP_202_ACCEPTED)
def retry_item(item_id: uuid.UUID, user: User = Depends(get_current_user),
               db: Session = Depends(get_db), queue: JobQueue = Depends(get_queue)):
    """Why: a failed or needs-review photo gets another go (e.g. after Ollama is restarted).
    202 = "accepted, will be processed", not "done".

    Examples:
      failed item          -> 202, status back to "queued", pushed to the worker
      done item            -> 202, re-generated (the user's edited fields stay)
      already queued/busy  -> 409 "already being processed"
      double-click Retry   -> first 202, second 409 (only ONE re-run)
    """
    item = _item_or_404(db, item_id, user)
    # Concept: ATOMIC COMPARE-AND-SET. One UPDATE that only succeeds if the item
    # isn't busy. Two simultaneous clicks: the DB lets exactly one win.
    result = db.execute(
        update(Item)
        .where(Item.id == item.id, Item.status.not_in(BUSY))
        .values(status=ItemStatus.QUEUED, last_error=None)
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This photo is already being processed.")
    db.commit()
    try:
        queue.push([item.id])                       # after commit, like the upload
    except redis.RedisError:
        logger.warning("Redis push failed for retry of %s; sweep will re-queue", item.id)
    db.refresh(item)
    return item


@router.get("/{item_id}/image")
def item_image(item_id: uuid.UUID, kind: Literal["clean", "original"] = "clean",
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Why: the review screen shows the photo; only its owner may see it.

    Examples:
      GET /items/{id}/image                 -> the clean white-background JPEG
      GET /items/{id}/image?kind=original   -> the uploaded photo
      clean image not made yet              -> 404 "Image not ready yet."
      someone else's item                   -> 404
    """
    item = _item_or_404(db, item_id, user)
    rel = item.clean_path if kind == "clean" else item.stored_path
    if not rel or not absolute_path(rel).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not ready yet.")
    return FileResponse(
        absolute_path(rel),
        media_type="image/png" if rel.endswith(".png") else "image/jpeg",
        headers={
            # Concept: NOSNIFF. The browser must trust our content type and never
            # "guess" a file is HTML/script (the deferred item from upload file 2)
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",   # this user's browser may cache it; shared caches may not
        },
    )
