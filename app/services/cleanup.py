# Concept: this file is PURE image work. No database, no Redis.
# Bytes in -> clean JPEG bytes out, so it's easy to test on its own.
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps

from app.core.config import settings

CANVAS_PX = 2048          # final image is 2048 x 2048
PRODUCT_FILL = 0.85       # product takes 85% of the canvas: a white margin around it
MAX_INPUT_PX = 2048       # shrink big photos BEFORE rembg (faster, less memory)
MIN_PRODUCT_SHARE = 0.01  # cutout under 1% of the photo = rembg found nothing real


class EmptyCutout(Exception):
    """rembg removed (almost) everything. The item goes to needs_review."""


@lru_cache(maxsize=1)
def _rembg_session():
    """Why: loading the AI model takes seconds; do it ONCE per worker, not per photo.
    Concept: lru_cache(maxsize=1) = run the first time, then return the saved result.
    Example: photo 1 loads the model (~2 s); photos 2-50 reuse it (0 s).
    Model comes from settings.rembg_model (default isnet-general-use, chosen in
    experiments/2026-11-14_rembg_models). First use downloads it to ~/.rembg/models/."""
    from rembg import new_session   # imported here so tests never load the model
    return new_session(settings.rembg_model)


def remove_background(img: Image.Image) -> Image.Image:
    """Why: the real background remover. Tests pass a fake instead.
    Example: photo of a shirt on a bed -> same shirt, bed now transparent (RGBA)."""
    from rembg import remove
    return remove(img, session=_rembg_session())


def prepare(data: bytes) -> Image.Image:
    """Why: phone photos arrive sideways, in odd colour modes, or huge.
    Fix all three so rembg always gets an upright, RGB, <= 2048 px image.

    Examples:
      iPhone photo stored sideways + rotation tag  -> rotated upright
      CMYK JPEG from a designer                    -> RGB
      PNG with transparent background              -> placed on white first
      8000x6000 photo                              -> shrunk to 2048x1536
    """
    with Image.open(BytesIO(data)) as img:
        # Concept: EXIF ORIENTATION. Cameras save pixels as shot plus a
        # "rotate me" tag; exif_transpose applies the tag to the pixels.
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            # Transparent PNG: convert("RGB") would turn transparent areas BLACK,
            # so put it on white first
            rgba = img.convert("RGBA")
            img = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
        img = img.convert("RGB")
        # Concept: thumbnail() shrinks in place, keeps the aspect ratio, never enlarges
        img.thumbnail((MAX_INPUT_PX, MAX_INPUT_PX), Image.LANCZOS)
        return img


def make_clean_image(data: bytes, remover=remove_background) -> bytes:
    """Why: the product photo sellers actually need. Product centred on white.

    Example: 3000x4000 photo of a dress on a hanger
      prepare        -> 1536x2048 upright RGB
      remover        -> dress kept, wall + hanger area transparent
      crop to dress  -> e.g. 900x1700
      scale to fit   -> 921x1740 (85% of 2048 on the long side)
      paste centred  -> 2048x2048 white JPEG
    Raises EmptyCutout if nothing real is left.
    """
    img = prepare(data)
    cutout = remover(img).convert("RGBA")

    # Concept: ALPHA CHANNEL = how see-through each pixel is (0 invisible, 255 solid).
    # Count only clearly visible pixels (> 20) to ignore faint leftover haze.
    mask = cutout.getchannel("A").point(lambda a: 255 if a > 20 else 0)
    visible = mask.histogram()[255]          # number of solid pixels
    if visible < MIN_PRODUCT_SHARE * img.width * img.height:
        raise EmptyCutout("Background removal found no product in this photo.")

    # Concept: BOUNDING BOX = the smallest rectangle around the product
    product = cutout.crop(mask.getbbox())
    scale = (CANVAS_PX * PRODUCT_FILL) / max(product.size)
    product = product.resize(
        (max(1, round(product.width * scale)), max(1, round(product.height * scale))),
        Image.LANCZOS,                        # high-quality resize filter
    )

    canvas = Image.new("RGB", (CANVAS_PX, CANVAS_PX), "white")
    offset = ((CANVAS_PX - product.width) // 2, (CANVAS_PX - product.height) // 2)
    canvas.paste(product, offset, mask=product)   # mask = use product's own transparency

    out = BytesIO()
    canvas.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()
