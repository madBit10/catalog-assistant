"""Worker scenarios (SYSTEM_DESIGN.md §6): what happens to a photo after upload."""
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
import redis
from PIL import Image
from sqlalchemy import update

from app.db.models import Batch, Item, ItemCategory, ItemStatus, User
from app.services.ai import AIError, AIResult, CatalogListing
from app.services.queue import JobQueue, _redis
from app.services.storage import absolute_path, save_clean, save_original
from app.worker import process_item, sweep


SHIRT = CatalogListing(is_product=True, title="Navy Cotton T-Shirt",
                       description="A navy crew-neck t-shirt.", category="men",
                       colours=["navy"], tags=["t-shirt", "cotton"])
NOT_CLOTHING = CatalogListing(is_product=False, title="water bottle", description="",
                              category="none", colours=[], tags=[])


class FakeAI:
    """Why: tests must never call Ollama or Claude (slow, costs money, unpredictable).
    Example: FakeAI()                       -> always answers SHIRT
             FakeAI(NOT_CLOTHING)           -> "this isn't clothing"
             FakeAI(error=AIError(..., transient=True)) -> acts like the AI is down"""
    def __init__(self, listing=SHIRT, error=None):
        self.listing, self.error, self.calls = listing, error, 0

    def describe(self, clean_jpeg):
        self.calls += 1
        if self.error:
            raise self.error
        return AIResult(listing=self.listing, model="fake/test", input_tokens=100, output_tokens=20)


def keep_centre(img):
    """Fake rembg: keeps the middle of the photo, makes the edges transparent."""
    out = img.convert("RGBA")
    alpha = Image.new("L", img.size, 0)
    w, h = img.size
    alpha.paste(255, (w // 4, h // 4, 3 * w // 4, 3 * h // 4))
    out.putalpha(alpha)
    return out


def remove_everything(img):
    """Fake rembg that finds no product (e.g. a photo of an empty wall)."""
    return Image.new("RGBA", img.size, (0, 0, 0, 0))


class CrashingRemover:
    """Fake rembg that crashes the first `crashes` times, then works."""
    def __init__(self, crashes):
        self.crashes, self.calls = crashes, 0

    def __call__(self, img):
        self.calls += 1
        if self.calls <= self.crashes:
            raise RuntimeError("onnxruntime: out of memory (simulated)")
        return keep_centre(img)


def queued_item(db, status=ItemStatus.QUEUED):
    """A user + batch + one uploaded photo on disk, like after POST /batches."""
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x" * 60)
    db.add(user)
    db.flush()
    batch = Batch(user_id=user.id, idempotency_key=uuid.uuid4().hex)
    db.add(batch)
    db.flush()
    buf = BytesIO()
    Image.new("RGB", (800, 600), "navy").save(buf, "JPEG")
    item = Item(batch_id=batch.id, original_filename="shirt.jpg",
                stored_path=save_original(buf.getvalue(), "jpg"), status=status)
    db.add(item)
    db.commit()
    return item


def test_photo_is_cleaned_and_marked_done(db):
    item = queued_item(db)
    assert process_item(db, str(item.id), keep_centre, FakeAI()) == ItemStatus.DONE
    db.refresh(item)
    assert item.attempts == 1 and item.last_error is None
    with Image.open(absolute_path(item.clean_path)) as clean:
        assert clean.size == (2048, 2048) and clean.getpixel((5, 5)) == (255, 255, 255)


def test_photo_with_no_product_goes_to_needs_review(db):
    item = queued_item(db)
    assert process_item(db, str(item.id), remove_everything, FakeAI()) == ItemStatus.NEEDS_REVIEW
    db.refresh(item)
    assert "found no product" in item.last_error and item.clean_path is None


def test_background_removal_crash_is_retried_once_then_succeeds(db):
    item = queued_item(db)
    remover = CrashingRemover(crashes=1)
    assert process_item(db, str(item.id), remover, FakeAI()) == ItemStatus.DONE
    assert remover.calls == 2


def test_background_removal_failing_twice_marks_failed(db):
    item = queued_item(db)
    remover = CrashingRemover(crashes=5)
    assert process_item(db, str(item.id), remover, FakeAI()) == ItemStatus.FAILED
    db.refresh(item)
    assert remover.calls == 2                       # retried once, not forever
    assert "Click Retry" in item.last_error


def test_missing_original_photo_marks_failed(db):
    item = queued_item(db)
    absolute_path(item.stored_path).unlink()
    assert process_item(db, str(item.id), keep_centre, FakeAI()) == ItemStatus.FAILED
    db.refresh(item)
    assert "missing" in item.last_error


def test_finished_photo_is_not_processed_twice(db):
    # The sweep or crash recovery can deliver the same ID again
    item = queued_item(db, status=ItemStatus.DONE)
    remover = CrashingRemover(crashes=0)
    assert process_item(db, str(item.id), remover, FakeAI()) == ItemStatus.DONE
    assert remover.calls == 0                       # never touched


def test_deleted_or_garbage_ids_are_ignored(db):
    assert process_item(db, str(uuid.uuid4()), keep_centre, FakeAI()) is None     # batch deleted
    assert process_item(db, "not-a-uuid", keep_centre, FakeAI()) is None          # junk in the queue


def test_retry_replaces_the_old_clean_image(db):
    item = queued_item(db)
    old = save_clean(b"old clean image")
    # Set it on the OBJECT, not with a raw UPDATE: the session keeps loaded
    # objects in memory (identity map) and, with expire_on_commit=False,
    # wouldn't see a raw UPDATE. The real worker uses a fresh session per item.
    item.clean_path = old
    db.commit()
    process_item(db, str(item.id), keep_centre, FakeAI())
    db.refresh(item)
    assert item.clean_path != old and not absolute_path(old).exists()   # no orphan file


def test_sweep_requeues_items_stuck_in_queued(db, fake_queue):
    # Redis was down during the upload, 11 minutes ago
    item = queued_item(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.execute(update(Item).where(Item.id == item.id).values(updated_at=old))
    db.commit()
    assert sweep(db, fake_queue) == 1
    assert fake_queue.pushed == [[item.id]]
    assert sweep(db, fake_queue) == 0               # not re-pushed every minute


def test_sweep_leaves_fresh_items_alone(db, fake_queue):
    queued_item(db)                                 # uploaded just now
    assert sweep(db, fake_queue) == 0


def test_item_survives_worker_crash():
    # Real Redis: the worker claims an item, then "crashes" before ack
    try:
        _redis.ping()
    except redis.RedisError:
        pytest.skip("Redis not running")
    q = JobQueue(_redis, f"test:crash:{uuid.uuid4().hex}")
    try:
        q.push(["photo-1"])
        assert q.claim() == "photo-1"               # worker took it... then crashed (no ack)
        assert q.recover_orphans() == 1             # restart puts it back
        assert q.claim() == "photo-1"               # and it gets processed
    finally:
        _redis.delete(q.name, q.processing)


def test_clothing_photo_gets_a_listing_and_is_done(db):
    item = queued_item(db)
    assert process_item(db, str(item.id), keep_centre, FakeAI()) == ItemStatus.DONE
    db.refresh(item)
    assert item.title == "Navy Cotton T-Shirt" and item.category == ItemCategory.MEN
    assert item.colours == ["navy"] and item.is_product is True
    assert (item.model, item.input_tokens, item.output_tokens) == ("fake/test", 100, 20)


def test_non_clothing_photo_needs_review_but_keeps_clean_image(db):
    item = queued_item(db)
    assert process_item(db, str(item.id), keep_centre, FakeAI(NOT_CLOTHING)) == ItemStatus.NEEDS_REVIEW
    db.refresh(item)
    assert "doesn't look like a clothing item" in item.last_error
    assert item.category is None and absolute_path(item.clean_path).exists()


def test_ai_down_marks_failed_but_keeps_clean_image(db):
    item = queued_item(db)
    down = FakeAI(error=AIError("The local AI (Ollama) isn't reachable. Is it running?", transient=True))
    assert process_item(db, str(item.id), keep_centre, down) == ItemStatus.FAILED
    db.refresh(item)
    assert "isn't reachable" in item.last_error and absolute_path(item.clean_path).exists()


def test_unusable_ai_answer_needs_review(db):
    item = queued_item(db)
    bad = FakeAI(error=AIError("The AI returned an answer we couldn't use.", transient=False))
    assert process_item(db, str(item.id), keep_centre, bad) == ItemStatus.NEEDS_REVIEW


def test_retry_does_not_overwrite_user_edits(db):
    # The user fixed the title, then clicked Retry
    item = queued_item(db)
    item.title, item.edited_fields = "My Own Title", ["title"]
    db.commit()
    process_item(db, str(item.id), keep_centre, FakeAI())
    db.refresh(item)
    assert item.title == "My Own Title"            # the user's edit survives
    assert item.tags == ["t-shirt", "cotton"]      # other fields still filled by AI


def test_ai_is_not_called_when_cleanup_finds_nothing(db):
    # No product in the photo -> don't waste an AI call (time, or money with Claude)
    item = queued_item(db)
    ai = FakeAI()
    process_item(db, str(item.id), remove_everything, ai)
    assert ai.calls == 0
