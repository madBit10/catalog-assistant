"""Review-screen scenarios: fixing AI text, retrying photos, viewing images (SYSTEM_DESIGN.md §6)."""
from sqlalchemy import update

from app.db.models import Item, ItemStatus
from app.services.storage import save_clean
from tests.conftest import register_and_login
from tests.test_batches import photo


def uploaded_item(client, headers, key="k-1"):
    """Why: a real upload through the API; returns the new item's id (status "queued")."""
    r = client.post("/batches", files=[photo()], headers={**headers, "Idempotency-Key": key})
    return r.json()["items"][0]["id"]


def set_item(db, item_id, **values):
    """Why: pretend the worker already ran (e.g. status=DONE) without running it.
    Example: set_item(db, id, status=ItemStatus.FAILED, last_error="AI busy")"""
    db.execute(update(Item).where(Item.id == item_id).values(**values))
    db.commit()


# ---------- Editing (PATCH) ----------

def test_user_can_fix_the_ai_title(client, db):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.DONE, title="mens motivational t-shirt")
    r = client.patch(f"/items/{item_id}", json={"title": "Mindset Is Everything Tee"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Mindset Is Everything Tee" and r.json()["edited_fields"] == ["title"]


def test_edits_add_up_across_requests(client, db):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.DONE)
    client.patch(f"/items/{item_id}", json={"title": "New Title"}, headers=headers)
    r = client.patch(f"/items/{item_id}", json={"tags": [" Tee", "tee", "Cotton"]}, headers=headers)
    assert r.json()["edited_fields"] == ["tags", "title"]     # both remembered
    assert r.json()["tags"] == ["tee", "cotton"]               # cleaned like AI output


def test_empty_edit_is_rejected(client, db):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.DONE)
    assert client.patch(f"/items/{item_id}", json={}, headers=headers).status_code == 422


def test_user_cannot_edit_protected_fields(client, db):
    # Mass assignment: trying to mark your own photo "done" or point it at another file
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.FAILED)
    for bad in ({"status": "done"}, {"stored_path": "../../etc/passwd"}):
        assert client.patch(f"/items/{item_id}", json=bad, headers=headers).status_code == 422


def test_cannot_edit_while_photo_is_processing(client):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)                   # still "queued"
    r = client.patch(f"/items/{item_id}", json={"title": "Too early"}, headers=headers)
    assert r.status_code == 409 and "still being processed" in r.text


def test_user_cannot_edit_another_users_item(client, db):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    item_id = uploaded_item(client, alice)
    set_item(db, item_id, status=ItemStatus.DONE)
    assert client.patch(f"/items/{item_id}", json={"title": "Hacked"}, headers=bob).status_code == 404


# ---------- Retry ----------

def test_failed_photo_can_be_retried(client, db, fake_queue):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.FAILED, last_error="The AI service is busy right now.")
    r = client.post(f"/items/{item_id}/retry", headers=headers)
    assert r.status_code == 202
    assert r.json()["status"] == "queued" and r.json()["last_error"] is None
    assert [str(i) for i in fake_queue.pushed[-1]] == [item_id]   # handed to the worker again


def test_double_click_retry_runs_only_once(client, db, fake_queue):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.FAILED)
    pushes_before = len(fake_queue.pushed)
    first = client.post(f"/items/{item_id}/retry", headers=headers)
    second = client.post(f"/items/{item_id}/retry", headers=headers)
    assert (first.status_code, second.status_code) == (202, 409)
    assert len(fake_queue.pushed) == pushes_before + 1


def test_retry_of_another_users_item_is_404(client, db):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    item_id = uploaded_item(client, alice)
    set_item(db, item_id, status=ItemStatus.FAILED)
    assert client.post(f"/items/{item_id}/retry", headers=bob).status_code == 404


# ---------- Images ----------

def test_owner_sees_clean_image_safely(client, db):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    set_item(db, item_id, status=ItemStatus.DONE, clean_path=save_clean(b"\xff\xd8 fake jpeg"))
    r = client.get(f"/items/{item_id}/image", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_original_photo_is_available(client):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)
    assert client.get(f"/items/{item_id}/image?kind=original", headers=headers).status_code == 200


def test_clean_image_not_ready_yet_is_404(client):
    headers = register_and_login(client)
    item_id = uploaded_item(client, headers)                   # worker hasn't run
    r = client.get(f"/items/{item_id}/image", headers=headers)
    assert r.status_code == 404 and "not ready" in r.text


def test_other_user_cannot_see_image(client):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    item_id = uploaded_item(client, alice)
    assert client.get(f"/items/{item_id}/image?kind=original", headers=bob).status_code == 404
