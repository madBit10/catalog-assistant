from io import BytesIO

from PIL import Image

# Formats we accept, mapped to the extension we store them with.
# Concept: MPO = a JPEG with extra embedded pictures (iPhone HDR/depth).
# Its first picture is a normal JPEG, so we store it as .jpg.
# Example: IMG_6028.JPG from an iPhone -> Pillow says "MPO" -> accepted as "jpg"
ALLOWED_FORMATS = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png"}
MAX_PIXELS = 50_000_000      # 8000x6000 phone photo = 48 MP; bigger = memory risk
MIN_SIDE_PX = 500            # smaller looks blurry on a 2048 px canvas


class InvalidImage(Exception):
    """A file that can't be processed. The message is shown to the user."""


def _looks_like_heic(data: bytes) -> bool:
    # HEIC files have "ftyp" at byte 4 followed by a HEIF brand
    return data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"hevc"}


def validate_image(data: bytes) -> str:
    """Check the file's real contents (not its name). Returns the extension to
    store it with, or raises InvalidImage with a message for the user."""
    if not data:
        raise InvalidImage("This file is empty. Please choose the photo again.")
    if _looks_like_heic(data):
        raise InvalidImage("iPhone HEIC photos aren't supported yet. Please export it as JPEG and upload again.")
    try:
        # verify() checks the file structure cheaply, without decoding pixels
        with Image.open(BytesIO(data)) as img:
            img.verify()
            fmt, (width, height) = img.format, img.size
    except Image.DecompressionBombError:
        # Pillow refuses images over ~179 megapixels: a "zip bomb" for images
        raise InvalidImage("This image's dimensions are too large to process.")
    except Exception:
        # Renamed PDF, text file, random bytes
        raise InvalidImage("This file isn't a valid image. Please upload a JPEG or PNG photo.")

    if fmt not in ALLOWED_FORMATS:
        raise InvalidImage(f"{fmt} images aren't supported. Please upload a JPEG or PNG photo.")
    # Check the size BEFORE decoding pixels, so a huge image never fills memory
    if width * height > MAX_PIXELS:
        raise InvalidImage("This image is too large (over 50 megapixels). Please resize it and try again.")
    if min(width, height) < MIN_SIDE_PX:
        raise InvalidImage(
            f"This photo is too small ({width}x{height}). "
            f"Please upload one at least {MIN_SIDE_PX} px on each side."
        )

    try:
        # Decode the pixels to catch truncated files that verify() misses
        # (verify() leaves the image unusable, hence a second open)
        with Image.open(BytesIO(data)) as img:
            img.load()
    except Exception:
        raise InvalidImage("This photo looks damaged or incomplete. Please upload it again.")
    return ALLOWED_FORMATS[fmt]
