"""Export scenarios (SYSTEM_DESIGN.md §6): the CSV and zip a seller downloads."""
import csv
import io
import zipfile

from sqlalchemy import update

from app.db.models import Item, ItemStatus
from app.services.storage import save_clean
from tests.conftest import register_and_login
from tests.test_batches import photo


def batch_with_items(client, headers, n=1, key="exp-1"):
    """Why: a real upload of n photos; returns (batch_id, [item_ids])."""
    body = client.post("/batches", files=[photo(f"p{i}.jpg") for i in range(n)],
                       headers={**headers, "Idempotency-Key": key}).json()
    return body["id"], [i["id"] for i in body["items"]]


def finish(db, item_id, **values):
    """Why: pretend the worker finished: status done + a real clean image on disk."""
    db.execute(update(Item).where(Item.id == item_id)
               .values(status=ItemStatus.DONE, clean_path=save_clean(b"\xff\xd8 jpeg"), **values))
    db.commit()


def csv_rows(response):
    """Parse the downloaded CSV the way a spreadsheet would."""
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_csv_survives_commas_quotes_and_accents(client, db):
    headers = register_and_login(client)
    batch_id, [item_id] = batch_with_items(client, headers)
    finish(db, item_id, title='Tee, "Best" Édition', description="Line one.\nLine two.")
    r = client.get(f"/batches/{batch_id}/export.csv", headers=headers)
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")   # BOM for Excel
    row = csv_rows(r)[0]
    assert row["title"] == 'Tee, "Best" Édition'           # comma, quotes, accent intact
    assert row["description"] == "Line one.\nLine two."     # line break intact


def test_csv_formula_injection_is_neutralised(client, db):
    headers = register_and_login(client)
    batch_id, [item_id] = batch_with_items(client, headers)
    finish(db, item_id, title='=HYPERLINK("http://evil.example","click")', tags=["@cmd"])
    row = csv_rows(client.get(f"/batches/{batch_id}/export.csv", headers=headers))[0]
    assert row["title"].startswith("'=")                    # shown as text, never run
    assert row["tags"] == "'@cmd"


def test_csv_and_zip_use_matching_file_names(client, db):
    headers = register_and_login(client)
    batch_id, ids = batch_with_items(client, headers, n=2)
    finish(db, ids[0], title="Navy Tee")
    finish(db, ids[1], title="Navy Tee")                    # same title twice
    names_in_csv = [r["image_file"] for r in csv_rows(client.get(f"/batches/{batch_id}/export.csv", headers=headers))]
    zip_bytes = client.get(f"/batches/{batch_id}/images.zip", headers=headers).content
    assert sorted(zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()) == sorted(names_in_csv)
    assert len(set(names_in_csv)) == 2                      # numbered, so no clash


def test_zip_entry_names_cannot_escape_the_folder(client, db):
    headers = register_and_login(client)
    batch_id, [item_id] = batch_with_items(client, headers)
    finish(db, item_id, title="../../etc/passwd")
    zip_bytes = client.get(f"/batches/{batch_id}/images.zip", headers=headers).content
    [name] = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
    assert "/" not in name and ".." not in name             # zip slip impossible


def test_unfinished_photos_are_in_csv_but_not_in_zip(client, db):
    headers = register_and_login(client)
    batch_id, ids = batch_with_items(client, headers, n=2)
    finish(db, ids[0], title="Done Tee")                    # ids[1] stays "queued"
    rows = csv_rows(client.get(f"/batches/{batch_id}/export.csv", headers=headers))
    # Upload order is guaranteed (items.position), so the row order is exact
    assert [r["status"] for r in rows] == ["done", "queued"] and rows[1]["image_file"] == ""
    zip_bytes = client.get(f"/batches/{batch_id}/images.zip", headers=headers).content
    assert len(zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()) == 1


def test_zip_with_nothing_finished_is_404(client):
    headers = register_and_login(client)
    batch_id, _ = batch_with_items(client, headers)
    r = client.get(f"/batches/{batch_id}/images.zip", headers=headers)
    assert r.status_code == 404 and "No finished images" in r.text


def test_downloads_are_saved_as_files(client, db):
    headers = register_and_login(client)
    batch_id, [item_id] = batch_with_items(client, headers)
    finish(db, item_id)
    for path in ("export.csv", "images.zip"):
        r = client.get(f"/batches/{batch_id}/{path}", headers=headers)
        assert r.headers["content-disposition"].startswith("attachment;")


def test_other_user_cannot_export(client, db):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    batch_id, [item_id] = batch_with_items(client, alice)
    finish(db, item_id)
    assert client.get(f"/batches/{batch_id}/export.csv", headers=bob).status_code == 404
    assert client.get(f"/batches/{batch_id}/images.zip", headers=bob).status_code == 404
