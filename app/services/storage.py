import os
import uuid
from pathlib import Path

from app.core.config import settings


def absolute_path(relative_path: str) -> Path:
    """DB stores paths relative to storage_dir; this turns one into a real path."""
    return Path(settings.storage_dir) / relative_path


def _save(data: bytes, folder: str, ext: str) -> str:
    """Why: one safe way to write any file: random name + temp file + rename.
    Concept: DRY. Originals and clean images share this code, so a fix lands once.
    Example: _save(b"...", "clean", "jpg") -> "clean/7a1e...c4.jpg" """
    target_dir = Path(settings.storage_dir) / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    # Name is 100% ours: a random UUID + an extension we chose (never the user's)
    name = f"{uuid.uuid4().hex}.{ext}"
    final = target_dir / name
    # Write to a temp file, then rename: a crash mid-write never leaves a
    # half-written photo under the real name (rename is atomic on one disk)
    tmp = final.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, final)
    return f"{folder}/{name}"


def save_original(data: bytes, ext: str) -> str:
    """Why: uploads. Example: save_original(photo, "png") -> "originals/3f9c...e1.png" """
    return _save(data, "originals", ext)


def save_clean(data: bytes) -> str:
    """Why: the worker's output, always JPEG.
    Example: save_clean(clean_bytes) -> "clean/7a1e...c4.jpg" """
    return _save(data, "clean", "jpg")


def delete_files(relative_paths: list[str]) -> None:
    """Remove files, ignoring ones already gone. Used to clean up after a
    failed upload, and later when a batch is deleted (CASCADE removes rows only)."""
    for rel in relative_paths:
        absolute_path(rel).unlink(missing_ok=True)
