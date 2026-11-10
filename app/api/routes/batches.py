import logging
import uuid

import redis
from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Batch, Item, User
from app.schemas.batches import BatchOut, BatchSummary, Progress, RejectedFile
from app.services.images import InvalidImage, validate_image
from app.services.ownership import get_batch_for_user
from app.services.queue import JobQueue, get_queue
from app.services.storage import delete_files, save_original

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batches", tags=["batches"])


def _progress(db: Session, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, Progress]:
    """Why: the progress bar needs status counts, and we COUNT them instead of
    storing counters (Decision Q1), so they can never drift.

    Example: batch A has 2 done + 1 queued, batch B has 1 failed
      _progress(db, [A, B]) ->
        {A: Progress(total=3, done=2, queued=1), B: Progress(total=1, failed=1)}
    """
    # Concept: GROUP BY counts for MANY batches in ONE query
    # (avoids N+1: one query per batch)
    counts = {bid: Progress() for bid in batch_ids}
    if not batch_ids:
        return counts
    rows = db.execute(
        select(Item.batch_id, Item.status, func.count())
        .where(Item.batch_id.in_(batch_ids))
        .group_by(Item.batch_id, Item.status)
    ).all()
    # rows look like: [(A, done, 2), (A, queued, 1), (B, failed, 1)]
    for batch_id, item_status, n in rows:
        setattr(counts[batch_id], item_status.value, n)  # e.g. counts[A].done = 2
        counts[batch_id].total += n
    return counts


def _batch_out(db: Session, batch: Batch, rejected: list[RejectedFile] | None = None) -> BatchOut:
    """Why: three endpoints return a full batch; one builder keeps them identical.

    Example: batch with 2 photos, 1 rejected file at upload
      -> {"id": ..., "progress": {"total": 2, "queued": 2, ...},
          "items": [{...shirt.jpg...}, {...dress.png...}],
          "rejected": [{"filename": "cv.pdf", "reason": "This file isn't a valid image..."}]}
    """
    items = db.scalars(select(Item).where(Item.batch_id == batch.id).order_by(Item.created_at)).all()
    return BatchOut(
        id=batch.id,
        created_at=batch.created_at,
        progress=_progress(db, [batch.id])[batch.id],
        items=items,
        rejected=rejected or [],
    )


def _existing_batch(db: Session, user: User, key: str) -> Batch | None:
    """Why: spot a repeated upload (double-click, network retry) by its key.

    Example: Alice uploads with key "k-123", then clicks again with "k-123"
      first call  -> None (new upload)
      second call -> the batch from the first click
    Bob using "k-123" -> None (keys are per user)
    """
    return db.scalar(select(Batch).where(Batch.user_id == user.id, Batch.idempotency_key == key))


# Concept: plain `def`, not `async def`. Pillow checks are CPU work that would
# freeze an async server; FastAPI runs plain `def` routes in a thread pool.
@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def upload_batch(
    response: Response,
    # Concept: Swagger UI only shows a file button for "format: binary".
    # FastAPI writes the newer OpenAPI 3.1 style, so we override the docs schema.
    # This changes only /docs. Uploads work the same either way.
    files: list[UploadFile] = File(
        ...,
        json_schema_extra={"items": {"type": "string", "format": "binary"}},
    ),
    # Concept: IDEMPOTENCY KEY. Browser makes one per upload click;
    # a repeat with the same key returns the same batch.
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=64),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_queue),
):
    """Why: the user's one action. Accept photos, save the good ones, queue them
    for the worker, and reply in about 1 second (processing happens later).

    Examples:
      shirt.jpg + dress.png              -> 201, 2 items "queued", rejected: []
      shirt.jpg + cv.pdf (renamed .jpg)  -> 201, 1 item, rejected: [cv.pdf: not an image]
      only cv.pdf                        -> 422, nothing saved
      same request again (same key)      -> 200, the SAME batch, nothing saved twice
      51 photos                          -> 422 "Upload between 1 and 50 photos."
      Redis down                         -> 201 anyway; items wait in DB for the sweep
    """
    # 1. Double-click? Return the batch we already made (200, not 201)
    existing = _existing_batch(db, user, idempotency_key)
    if existing:
        response.status_code = status.HTTP_200_OK
        return _batch_out(db, existing)

    # 2. 1-50 files
    if not 1 <= len(files) <= settings.max_files_per_batch:
        raise HTTPException(422, f"Upload between 1 and {settings.max_files_per_batch} photos.")

    # 3. Check + save each file ONE AT A TIME (memory holds 1 photo, not 50)
    max_bytes = settings.max_file_mb * 1024 * 1024
    saved: list[tuple[str, str]] = []          # e.g. [("shirt.jpg", "originals/3f9c...e1.jpg")]
    rejected: list[RejectedFile] = []
    for f in files:
        name = (f.filename or "unnamed")[:255]  # display only; column limit is 255
        # Concept: CAPPED READ. Read at most limit + 1 byte; if we got the +1,
        # the file is too big, and we never loaded the rest of a 500 MB file
        data = f.file.read(max_bytes + 1)
        if len(data) > max_bytes:
            rejected.append(RejectedFile(filename=name, reason=f"File is larger than {settings.max_file_mb} MB."))
            continue
        try:
            ext = validate_image(data)
        except InvalidImage as e:
            rejected.append(RejectedFile(filename=name, reason=str(e)))
            continue
        saved.append((name, save_original(data, ext)))

    if not saved:
        raise HTTPException(422, {"message": "None of the files could be used.",
                                  "rejected": [r.model_dump() for r in rejected]})

    # 4. Batch + items in ONE transaction: all saved, or nothing
    batch = Batch(user_id=user.id, idempotency_key=idempotency_key)
    items = [Item(original_filename=n, stored_path=p) for n, p in saved]
    try:
        db.add(batch)
        db.flush()                      # sends the INSERT, so batch.id is usable; not committed yet
        for item in items:
            item.batch_id = batch.id
        db.add_all(items)
        db.commit()
    except IntegrityError:
        # Concept: RACE. Two clicks arrived at the same instant; both passed
        # step 1, but the unique (user_id, key) index let only one insert win.
        # Example: click A commits first -> click B lands here -> returns A's batch
        db.rollback()
        delete_files([p for _, p in saved])
        response.status_code = status.HTTP_200_OK
        return _batch_out(db, _existing_batch(db, user, idempotency_key))
    except Exception:
        db.rollback()
        delete_files([p for _, p in saved])     # no orphan photos on disk
        raise

    # 5. Queue AFTER commit, so the worker can always find the rows.
    # Concept: DUAL WRITE. If Redis fails here, items stay "queued" in the DB
    # and the sweep re-queues them, so the upload still succeeds.
    try:
        queue.push([item.id for item in items])
    except redis.RedisError:
        logger.warning("Redis push failed for batch %s; sweep will re-queue", batch.id)

    return _batch_out(db, batch, rejected)


@router.get("", response_model=list[BatchSummary])
def list_batches(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Why: the "My batches" page. Only this user's, newest first, with progress.

    Example: Alice has 2 batches, Bob has 5
      Alice calls -> [{today's batch, done 3/5}, {yesterday's, done 10/10}]  (never Bob's)
    """
    batches = db.scalars(
        select(Batch).where(Batch.user_id == user.id).order_by(Batch.created_at.desc()).limit(100)
    ).all()
    progress = _progress(db, [b.id for b in batches])   # 1 query for all, not 1 per batch
    return [BatchSummary(id=b.id, created_at=b.created_at, progress=progress[b.id]) for b in batches]


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Why: the batch page the browser polls every 2 s for live progress.

    Examples:
      Alice opens her batch        -> 200, items + progress
      Bob opens Alice's batch id   -> 404 "Batch not found."
      Anyone opens a made-up id    -> 404, same message (Bob can't tell the difference)
      /batches/not-a-uuid          -> 422 (FastAPI checks the UUID format)
    """
    batch = get_batch_for_user(db, batch_id, user)
    if batch is None:
        raise HTTPException(404, "Batch not found.")
    return _batch_out(db, batch)
