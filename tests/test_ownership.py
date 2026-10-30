"""A user must never reach another user's batch or item (SYSTEM_DESIGN.md §6, Decision Q2).
The routes come later; this tests the one helper they'll all use."""
import uuid

from app.db.models import Batch, Item, User
from app.services.ownership import get_batch_for_user, get_item_for_user


def _user_with_one_item(db, email):
    user = User(email=email, password_hash="x" * 60)
    db.add(user)
    db.flush()
    batch = Batch(user_id=user.id, idempotency_key=uuid.uuid4().hex)
    db.add(batch)
    db.flush()
    item = Item(batch_id=batch.id, original_filename="shirt.jpg", stored_path="s/1.jpg")
    db.add(item)
    db.commit()
    return user, batch, item


def test_owner_can_load_their_batch_and_item(db):
    alice, batch, item = _user_with_one_item(db, "alice@example.com")
    assert get_batch_for_user(db, batch.id, alice).id == batch.id
    assert get_item_for_user(db, item.id, alice).id == item.id


def test_user_cannot_see_another_users_batch(db):
    # Bob changes the id in the URL to Alice's
    alice, batch, item = _user_with_one_item(db, "alice@example.com")
    bob, _, _ = _user_with_one_item(db, "bob@example.com")
    assert get_batch_for_user(db, batch.id, bob) is None
    assert get_item_for_user(db, item.id, bob) is None


def test_someone_elses_id_looks_the_same_as_a_missing_id(db):
    alice, batch, _ = _user_with_one_item(db, "alice@example.com")
    bob, _, _ = _user_with_one_item(db, "bob@example.com")
    # Both None -> both become 404, so Bob can't learn Alice's batch exists
    assert get_batch_for_user(db, batch.id, bob) is get_batch_for_user(db, uuid.uuid4(), bob)
