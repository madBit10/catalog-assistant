# Concept: the WORKER is a separate process from the API.
# Run it with: python -m app.worker   (Ctrl+C stops it after the current photo)
import logging
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Item, ItemCategory, ItemStatus
from app.services.ai import AIClient, AIError, AIResult, get_ai_client
from app.services.cleanup import EmptyCutout, make_clean_image, remove_background
from app.services.queue import JobQueue, get_queue
from app.services.storage import absolute_path, delete_files, save_clean

logger = logging.getLogger("worker")

CLEANUP_TRIES = 2                    # rembg: try, retry once, then fail (retry policy)
STALE_AFTER = timedelta(minutes=10)  # "queued" this long = probably lost by Redis
SWEEP_EVERY_SECONDS = 60
NOT_CLOTHING = ("This photo doesn't look like a clothing item, so no listing was written. "
                "Edit it yourself or upload a different photo.")


def _finish(db: Session, item: Item, status: ItemStatus, error: str | None) -> ItemStatus:
    """Why: every ending (done / needs_review / failed) saves the same way.
    Example: _finish(db, item, FAILED, "Original photo is missing.") -> FAILED"""
    item.status = status
    item.last_error = error
    db.commit()
    return status


def _apply_listing(item: Item, result: AIResult) -> None:
    """Why: copy the AI's answer onto the item, but NEVER over a field the user
    edited (Decision Q3: edited_fields).
    Example: user fixed the title earlier -> edited_fields = ["title"]
      AI returns a new title + tags -> title kept, tags updated"""
    listing = result.listing
    ai_fields = {
        "title": listing.title,
        "description": listing.description,
        "category": None if listing.category == "none" else ItemCategory(listing.category),
        "colours": listing.colours,
        "tags": listing.tags,
    }
    for name, value in ai_fields.items():
        if name not in item.edited_fields:
            setattr(item, name, value)
    item.is_product = listing.is_product
    # Cost tracking for the Ollama vs Claude comparison
    item.model, item.input_tokens, item.output_tokens = result.model, result.input_tokens, result.output_tokens


def process_item(db: Session, item_id: str, remover=remove_background, ai: AIClient | None = None) -> ItemStatus | None:
    """Why: turn ONE queued photo into a clean image and record the outcome.

    Examples:
      normal shirt photo        -> clean/....jpg saved, status DONE
      rembg finds nothing       -> NEEDS_REVIEW "found no product" (no retry: same photo, same result)
      rembg crashes once        -> retried, then DONE
      rembg crashes twice       -> FAILED "Background removal failed..."
      original file deleted     -> FAILED "original photo is missing"
      item already DONE         -> skipped (duplicate from the sweep or recovery)
      item's batch was deleted  -> None (nothing to do)
      AI says not clothing      -> NEEDS_REVIEW (clean image kept, no invented listing)
      AI busy / Ollama down     -> FAILED "Click Retry" (transient)
      AI answer unusable        -> NEEDS_REVIEW with the reason (permanent)
    """
    try:
        item = db.get(Item, uuid.UUID(item_id))
    except ValueError:                       # garbage in the queue: not a UUID
        logger.warning("Skipping invalid queue entry %r", item_id)
        return None
    if item is None:
        return None

    # Concept: IDEMPOTENT CONSUMER. The same ID may arrive twice (sweep or
    # crash recovery); finished items are skipped, so no photo is done twice.
    if item.status not in (ItemStatus.QUEUED, ItemStatus.PROCESSING):
        return item.status

    item.status = ItemStatus.PROCESSING      # the browser now shows "processing"
    item.attempts += 1
    db.commit()

    try:
        data = absolute_path(item.stored_path).read_bytes()
    except FileNotFoundError:
        return _finish(db, item, ItemStatus.FAILED, "The original photo is missing. Please upload it again.")

    # Concept: TRANSIENT vs PERMANENT. Would trying again change the result?
    for attempt in range(1, CLEANUP_TRIES + 1):
        try:
            clean = make_clean_image(data, remover)
            break
        except EmptyCutout as e:             # permanent: retrying gives the same answer
            return _finish(db, item, ItemStatus.NEEDS_REVIEW, str(e))
        except Exception:                    # unknown (e.g. a memory spike): retry once
            logger.exception("Cleanup failed for item %s (try %d)", item.id, attempt)
            if attempt == CLEANUP_TRIES:
                return _finish(db, item, ItemStatus.FAILED, "Background removal failed. Click Retry to try again.")

    old_clean = item.clean_path              # on a retry, replace the previous clean image
    item.clean_path = save_clean(clean)

    ai = ai or get_ai_client()
    try:
        result = ai.describe(clean)
    except AIError as e:
        # Concept: TRANSIENT -> failed, user can Retry later; PERMANENT -> needs a human
        status = _finish(db, item, ItemStatus.FAILED if e.transient else ItemStatus.NEEDS_REVIEW, str(e))
    else:
        _apply_listing(item, result)
        if result.listing.is_product:
            status = _finish(db, item, ItemStatus.DONE, None)
        else:
            status = _finish(db, item, ItemStatus.NEEDS_REVIEW, NOT_CLOTHING)

    if old_clean:
        delete_files([old_clean])
    return status


def sweep(db: Session, queue: JobQueue) -> int:
    """Why: the API commits to the DB, then pushes to Redis. If that push failed
    (dual write), items sit "queued" forever. The sweep re-queues them.

    Example: Redis was down during an upload at 10:00
      10:11 sweep -> finds 3 items queued since 10:00 -> pushes them -> returns 3
    A re-pushed item that's already queued is harmless: the idempotency check skips it.
    """
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    stale_ids = db.scalars(
        select(Item.id).where(Item.status == ItemStatus.QUEUED, Item.updated_at < cutoff)
    ).all()
    if stale_ids:
        queue.push(stale_ids)
        # Touch updated_at, so the next sweep doesn't push them again a minute later
        db.execute(update(Item).where(Item.id.in_(stale_ids)).values(updated_at=datetime.now(timezone.utc)))
        db.commit()
        logger.info("Sweep re-queued %d stale item(s)", len(stale_ids))
    return len(stale_ids)


def run(queue: JobQueue | None = None) -> None:
    """Why: the main loop. Recover, then claim -> process -> ack, forever.

    Example run:
      start          -> "Recovered 1 orphaned item(s)" (it crashed last time)
      queue empty    -> claim() waits 2 s, returns None, loop again
      item arrives   -> processed -> ack -> next
      Ctrl+C         -> finishes the current photo, then exits cleanly
    """
    queue = queue or get_queue()
    ai = get_ai_client()          # one HTTP connection pool / SDK client for the whole run
    stopping = False

    # Concept: GRACEFUL SHUTDOWN. Ctrl+C (SIGINT) or a deploy (SIGTERM) sets a
    # flag instead of killing mid-photo; the loop exits after the current item.
    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True
        logger.info("Stopping after the current item...")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    logger.info("Recovered %d orphaned item(s)", queue.recover_orphans())
    last_sweep = 0.0

    while not stopping:
        try:
            # Concept: time.monotonic() only goes forward (unlike the wall
            # clock, which can jump when the system time changes)
            if time.monotonic() - last_sweep > SWEEP_EVERY_SECONDS:
                with SessionLocal() as db:
                    sweep(db, queue)
                last_sweep = time.monotonic()

            item_id = queue.claim()
            if item_id is None:
                continue                     # nothing to do; ask again

            with SessionLocal() as db:
                process_item(db, item_id, ai=ai)
            queue.ack(item_id)               # ONLY after the outcome is saved
        except redis.RedisError:
            logger.warning("Redis unavailable; retrying in 5 s")
            time.sleep(5)
        except Exception:
            # e.g. the DB is down: no ack, so the item stays in "processing"
            # and recover_orphans() re-queues it on the next start
            logger.exception("Unexpected error; continuing")
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
