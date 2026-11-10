# Concept: a QUEUE lets the API hand off slow work and reply right away.
import uuid

import redis

from app.core.config import settings

# Concept: one shared client = a pool of reusable connections.
# It connects on first use, so a down Redis doesn't crash the import.
_redis = redis.Redis.from_url(
    settings.redis_url,
    socket_connect_timeout=2,   # Concept: FAIL FAST. Give up instead of hanging.
    socket_timeout=5,
    decode_responses=True,      # get str back, not bytes
)


class JobQueue:
    def __init__(self, client: redis.Redis, name: str):
        self.client = client
        self.name = name
        # Concept: IN-FLIGHT LIST. Items being worked on live here, not nowhere.
        self.processing = f"{name}:processing"

    def push(self, item_ids: list[uuid.UUID]) -> None:
        # Concept: send only IDs. The worker reads the latest data from the DB.
        if item_ids:  # Redis errors on an empty push
            # Concept: FIFO. Push left, worker takes right.
            # Concept: * UNPACKS a list into separate arguments (not a pointer):
            #   ids = ["a", "b"]
            #   lpush(name, ids)   -> ONE argument (a list), and Redis rejects it
            #   lpush(name, *ids)  -> lpush(name, "a", "b"), 1 trip for all IDs
            self.client.lpush(self.name, *[str(i) for i in item_ids])

    def claim(self, wait_seconds: int = 2) -> str | None:
        """Why: give the worker the next item WITHOUT losing it if the worker crashes.
        Concept: BLMOVE atomically moves an ID from the queue to the processing list
        in ONE step. A crash mid-work leaves the ID in "processing", not lost.
        Waits up to wait_seconds for work (must stay under socket_timeout=5).

        Example:
          queue=[id3, id2, id1], processing=[]
          claim() -> "id1"   queue=[id3, id2], processing=[id1]
          empty queue for 2 s -> None (the worker loops and asks again)
        """
        return self.client.blmove(self.name, self.processing, wait_seconds, "RIGHT", "LEFT")

    def ack(self, item_id: str) -> None:
        """Why: "done with this one". Called only AFTER the result is saved in the DB.
        Example: processing=[id1] -> ack("id1") -> processing=[]"""
        self.client.lrem(self.processing, 1, item_id)

    def recover_orphans(self) -> int:
        """Why: after a crash, items stuck in "processing" would never finish.
        On startup, move them back to the FRONT of the queue (the right end).
        Concept: only safe with ONE worker. A 2nd worker starting up would steal
        items the 1st is still working on (fine for v1; noted for scaling).

        Example: worker crashed during id1
          processing=[id1], queue=[id3, id2]
          recover_orphans() -> 1   queue=[id3, id2, id1] -> id1 is next
        """
        moved = 0
        while self.client.lmove(self.processing, self.name, "RIGHT", "RIGHT"):
            moved += 1
        return moved


def get_queue() -> JobQueue:
    # Concept: DEPENDENCY INJECTION. Tests swap this for a fake queue.
    return JobQueue(_redis, settings.queue_name)
