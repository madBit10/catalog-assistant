"""Real-user upload scenarios (SYSTEM_DESIGN.md §6). Uses the FakeQueue and a
temp storage folder from conftest, so no Redis and no real files are touched."""
import os
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import update

import app.api.routes.batches as batches_route
from app.core.config import settings
from app.db.models import Item, ItemStatus
from tests.conftest import register_and_login


def photo(name="shirt.jpg", fmt="JPEG", size=(800, 600)):
    """Why: a real, valid image in memory, shaped like an upload.
    Example: photo("dress.png", "PNG") -> ("files", ("dress.png", <bytes>, "image/png"))"""
    buf = BytesIO()
    Image.new("RGB", size, "white").save(buf, fmt)
    return ("files", (name, buf.getvalue(), f"image/{fmt.lower()}"))


def fake_jpg(name="cv.jpg"):
    """Why: the classic mistake, a PDF renamed to .jpg."""
    return ("files", (name, b"%PDF-1.7\n" * 50, "image/jpeg"))


def upload(client, headers, files, key="key-1"):
    return client.post("/batches", files=files, headers={**headers, "Idempotency-Key": key})


def stored_files():
    folder = Path(os.environ["STORAGE_DIR"]) / "originals"
    return sorted(folder.iterdir()) if folder.exists() else []


def test_upload_creates_queued_items_and_queues_them(client, fake_queue):
    headers = register_and_login(client)
    r = upload(client, headers, [photo("shirt.jpg"), photo("dress.png", "PNG")])
    assert r.status_code == 201
    body = r.json()
    assert body["progress"] == {"total": 2, "queued": 2, "processing": 0, "done": 0, "needs_review": 0, "failed": 0}
    assert len(stored_files()) == 2
    # Exactly these 2 items were handed to the worker, once
    assert [[str(i) for i in push] for push in fake_queue.pushed] == [[i["id"] for i in body["items"]]]


def test_fake_jpg_is_rejected_but_rest_of_batch_continues(client):
    headers = register_and_login(client)
    r = upload(client, headers, [photo("shirt.jpg"), fake_jpg("cv.jpg")])
    assert r.status_code == 201
    assert [i["original_filename"] for i in r.json()["items"]] == ["shirt.jpg"]
    assert r.json()["rejected"][0]["filename"] == "cv.jpg"
    assert "isn't a valid image" in r.json()["rejected"][0]["reason"]


def test_batch_of_only_bad_files_is_rejected_and_nothing_saved(client, fake_queue):
    headers = register_and_login(client)
    r = upload(client, headers, [fake_jpg("a.jpg"), fake_jpg("b.jpg")])
    assert r.status_code == 422
    assert len(r.json()["detail"]["rejected"]) == 2
    assert stored_files() == [] and fake_queue.pushed == []


def test_double_click_upload_creates_one_batch(client, fake_queue):
    headers = register_and_login(client)
    first = upload(client, headers, [photo()], key="click-1")
    second = upload(client, headers, [photo()], key="click-1")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(stored_files()) == 1          # second click saved nothing
    assert len(fake_queue.pushed) == 1       # and queued nothing


def test_two_clicks_at_the_same_instant_still_create_one_batch(client, monkeypatch):
    # Simulate the race: both requests pass the "seen this key?" check
    headers = register_and_login(client)
    upload(client, headers, [photo()], key="race")
    real_check = batches_route._existing_batch
    calls = {"n": 0}

    def miss_first_time(db, user, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_check(db, user, key)

    monkeypatch.setattr(batches_route, "_existing_batch", miss_first_time)
    r = upload(client, headers, [photo()], key="race")
    assert r.status_code == 200              # the unique index caught it
    assert len(stored_files()) == 1          # the loser's file was deleted


def test_same_key_from_two_users_creates_two_batches(client):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    a = upload(client, alice, [photo()], key="same")
    b = upload(client, bob, [photo()], key="same")
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


def test_weird_filenames_are_stored_safely(client):
    headers = register_and_login(client)
    names = ["../../etc/passwd.jpg", "shirt (1) é.jpg", "x" * 300 + ".jpg"]
    r = upload(client, headers, [photo(n) for n in names])
    assert r.status_code == 201
    # Display names kept (long one cut to 255), but files on disk have our random names
    shown = [i["original_filename"] for i in r.json()["items"]]
    assert shown[:2] == names[:2] and len(shown[2]) == 255
    root = Path(os.environ["STORAGE_DIR"]).resolve()
    for f in stored_files():
        assert f.resolve().parent == root / "originals"     # nothing escaped the folder
        assert len(f.stem) == 32                             # uuid4 hex


def test_empty_and_oversized_batches_are_rejected(client):
    headers = register_and_login(client)
    assert upload(client, headers, []).status_code == 422
    too_many = [photo(f"p{i}.jpg", size=(500, 500)) for i in range(51)]
    r = upload(client, headers, too_many)
    assert r.status_code == 422 and "between 1 and 50" in r.text
    assert stored_files() == []


def test_file_over_size_limit_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_file_mb", 1)
    headers = register_and_login(client)
    big = ("files", ("huge.jpg", b"x" * (1024 * 1024 + 1), "image/jpeg"))
    r = upload(client, headers, [photo(), big])
    assert r.status_code == 201
    assert "larger than 1 MB" in r.json()["rejected"][0]["reason"]


def test_upload_requires_login(client):
    r = client.post("/batches", files=[photo()], headers={"Idempotency-Key": "k"})
    assert r.status_code == 401


def test_upload_without_idempotency_key_is_rejected(client):
    headers = register_and_login(client)
    assert client.post("/batches", files=[photo()], headers=headers).status_code == 422


def test_upload_succeeds_even_if_redis_is_down(client, fake_queue):
    fake_queue.fail = True
    headers = register_and_login(client)
    r = upload(client, headers, [photo()])
    assert r.status_code == 201
    assert r.json()["items"][0]["status"] == "queued"   # waits for the sweep


def test_user_cannot_see_another_users_batch(client):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    batch_id = upload(client, alice, [photo()]).json()["id"]
    assert client.get(f"/batches/{batch_id}", headers=bob).status_code == 404
    assert client.get("/batches", headers=bob).json() == []      # not in Bob's list either
    assert client.get(f"/batches/{batch_id}", headers=alice).status_code == 200


def test_progress_is_computed_from_item_statuses(client, db):
    headers = register_and_login(client)
    body = upload(client, headers, [photo("a.jpg"), photo("b.jpg"), photo("c.jpg")]).json()
    ids = [i["id"] for i in body["items"]]
    # Pretend the worker finished one and failed one
    db.execute(update(Item).where(Item.id == ids[0]).values(status=ItemStatus.DONE))
    db.execute(update(Item).where(Item.id == ids[1]).values(status=ItemStatus.FAILED))
    db.commit()
    progress = client.get(f"/batches/{body['id']}", headers=headers).json()["progress"]
    assert (progress["total"], progress["done"], progress["failed"], progress["queued"]) == (3, 1, 1, 1)
    # Same numbers on the list page
    assert client.get("/batches", headers=headers).json()[0]["progress"] == progress
