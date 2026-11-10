import os
import uuid
from pathlib import Path

from app.core.config import settings


def absolute_path(relative_path: str) -> Path:
    """DB stores paths relative to storage_dir; this turns one into a real path."""
    return Path(settings.storage_dir) / relative_path


def save_original(data: bytes, ext: str) -> str:
    """Save an uploaded photo under a random name. Returns the path to store
    in items.stored_path, e.g. "originals/3f9c...e1.jpg"."""
    folder = Path(settings.storage_dir) / "originals"
    folder.mkdir(parents=True, exist_ok=True)
    # Name is 100% ours: a random UUID + the extension validate_image() returned
    name = f"{uuid.uuid4().hex}.{ext}"
    final = folder / name
    # Write to a temp file, then rename: a crash mid-write never leaves a
    # half-written photo under the real name (rename is atomic on one disk)
    tmp = final.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, final)
    return f"originals/{name}"


def delete_files(relative_paths: list[str]) -> None:
    """Remove files, ignoring ones already gone. Used to clean up after a
    failed upload, and later when a batch is deleted (CASCADE removes rows only)."""
    for rel in relative_paths:
        absolute_path(rel).unlink(missing_ok=True)
