import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Batch, Item, User

# The ONLY way routes load a batch or item by id (Decision Q2).
# Both return None for "doesn't exist" AND "belongs to someone else";
# the route turns None into 404, so an attacker can't tell the two apart.


def get_batch_for_user(db: Session, batch_id: uuid.UUID, user: User) -> Batch | None:
    return db.scalar(
        select(Batch).where(Batch.id == batch_id, Batch.user_id == user.id)
    )


def get_item_for_user(db: Session, item_id: uuid.UUID, user: User) -> Item | None:
    # Items have no user_id: the owner is reached through the batch
    return db.scalar(
        select(Item)
        .join(Batch, Item.batch_id == Batch.id)
        .where(Item.id == item_id, Batch.user_id == user.id)
    )
