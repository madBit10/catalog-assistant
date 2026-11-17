# Concept: PURE FUNCTIONS. Items in -> bytes out. No HTTP, no DB here,
# so every edge case (commas, accents, "=cmd") is easy to test directly.
import csv
import io
import re
import zipfile

from app.db.models import Item
from app.services.storage import absolute_path

CSV_COLUMNS = ["image_file", "original_filename", "status", "title", "description",
               "category", "colours", "tags"]
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    """Why: Excel runs any cell that starts with = + - @ as a FORMULA. AI or user text
    like "=HYPERLINK(...)" could run when the seller opens the file.
    Concept: CSV FORMULA INJECTION. Prefix such cells with ' so Excel shows them as text.
    Example: "=1+1" -> "'=1+1";  "Navy Tee" -> "Navy Tee";  None -> "" """
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def _slug(text: str) -> str:
    """Why: zip entry names come from titles, which are user/AI text.
    Only a-z, 0-9 and dashes survive, so "../../evil" can't escape the folder on unzip.
    Concept: ZIP SLIP. Never trust a file name inside an archive.
    Example: "Mindset Is EVERYTHING Tee!" -> "mindset-is-everything-tee";  "../../x" -> "x" """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "photo"


def image_names(items: list[Item]) -> dict:
    """Why: the CSV and the zip must use the SAME file name for each photo,
    so the seller can match rows to images.
    Example: [shirt (title "Navy Tee"), bottle (no title)]
      -> {shirt.id: "01-navy-tee.jpg", bottle.id: "02-bottle.jpg"}
    The number prefix keeps names unique even if two titles are the same."""
    names = {}
    for n, item in enumerate(items, start=1):
        base = item.title or item.original_filename.rsplit(".", 1)[0]
        names[item.id] = f"{n:02d}-{_slug(base)}.jpg"
    return names


def build_csv(items: list[Item]) -> bytes:
    """Why: the catalog as a spreadsheet, ready for a store import.

    Example row:
      01-navy-tee.jpg, shirt.jpg, done, Navy Tee, "A navy tee, 100% cotton.", men, navy, t-shirt; cotton
    - Commas, quotes and line breaks inside text are quoted correctly by the csv module.
    - Lists are joined with "; " (a comma would clash with the CSV separator).
    - Starts with a UTF-8 BOM, so Excel shows accents (é, ü) correctly.
    """
    names = image_names(items)
    buf = io.StringIO()
    writer = csv.writer(buf)                  # Concept: never build CSV by hand with ",".join()
    writer.writerow(CSV_COLUMNS)
    for item in items:
        writer.writerow([safe_cell(v) for v in [
            names[item.id] if item.clean_path else "",   # no clean image -> no file
            item.original_filename,
            item.status.value,
            item.title,
            item.description,
            item.category.value if item.category else "",
            "; ".join(item.colours),
            "; ".join(item.tags),
        ]])
    # Concept: BOM ("utf-8-sig"). Invisible marker bytes; without it Excel shows "Ã©" for "é"
    return buf.getvalue().encode("utf-8-sig")


def build_zip(items: list[Item]) -> bytes:
    """Why: all clean images in one download, named to match the CSV.
    Example: 3 done items -> zip with 01-navy-tee.jpg, 02-..., 03-...
    Items without a clean image (failed / still processing) are skipped.
    Concept: ZIP_STORED (no compression). JPEGs are already compressed;
    compressing again wastes CPU for ~0% size gain."""
    names = image_names(items)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for item in items:
            if item.clean_path and absolute_path(item.clean_path).exists():
                zf.write(absolute_path(item.clean_path), arcname=names[item.id])
    return buf.getvalue()
