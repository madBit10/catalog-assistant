"""Compare rembg models on the same photos, using our real pipeline (make_clean_image).

Why: u2net left wood inside a coiled cable and made thin/uncertain parts hazy.
Run (from the project root):  PYTHONPATH=. python experiments/2026-11-14_rembg_models/compare_models.py
      (PYTHONPATH=. lets the script import `app`; running a file by path only adds its own folder)
Out:  outputs/<model>/<photo>.jpg, grid.jpg, timings.json (next to this file)
"""
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw
from rembg import new_session, remove

from app.services.cleanup import make_clean_image

HERE = Path(__file__).parent
STORAGE = Path("storage/originals")
PHOTOS = {  # name -> stored original (uploaded 2026-11-10 / 11-14)
    "pencil_box": "d97a13306bf947ea9afd3090b60e6aab.jpg",
    "bottle": "d697dc19cfbe4864a197bbd59c9f4876.jpg",
    "cable": "79caf55989f343ebb12a135f3806e171.jpg",
    "people": "19e2c7f0a7c2421eb6e18cdec66ab988.jpg",
}
MODELS = ["u2net", "isnet-general-use", "birefnet-general-lite"]
THUMB = 400


def main():
    timings = {}
    for model in MODELS:
        t0 = time.perf_counter()
        session = new_session(model)          # downloads on first use
        load_s = time.perf_counter() - t0
        remover = lambda img, s=session: remove(img, session=s)
        out_dir = HERE / "outputs" / model
        out_dir.mkdir(parents=True, exist_ok=True)
        per_photo = {}
        for name, file in PHOTOS.items():
            data = (STORAGE / file).read_bytes()
            t = time.perf_counter()
            try:
                (out_dir / f"{name}.jpg").write_bytes(make_clean_image(data, remover))
                per_photo[name] = round(time.perf_counter() - t, 2)
            except Exception as e:             # e.g. EmptyCutout
                per_photo[name] = f"error: {e}"
        timings[model] = {"load_s": round(load_s, 1), "seconds_per_photo": per_photo}
        print(model, timings[model], flush=True)

    (HERE / "timings.json").write_text(json.dumps(timings, indent=2))

    # Grid: row 0 = originals, then one row per model
    cols, rows = len(PHOTOS), len(MODELS) + 1
    label_w = 230
    grid = Image.new("RGB", (label_w + cols * THUMB, rows * THUMB), "white")
    draw = ImageDraw.Draw(grid)
    for r, row_name in enumerate(["original"] + MODELS):
        draw.text((10, r * THUMB + THUMB // 2), row_name, fill="black")
        for c, name in enumerate(PHOTOS):
            path = STORAGE / PHOTOS[name] if r == 0 else HERE / "outputs" / row_name / f"{name}.jpg"
            if path.exists():
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((THUMB - 10, THUMB - 10))
                    grid.paste(im, (label_w + c * THUMB + 5, r * THUMB + 5))
    grid.save(HERE / "grid.jpg", quality=88)
    print("saved grid.jpg")


if __name__ == "__main__":
    main()
