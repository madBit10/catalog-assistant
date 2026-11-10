"""What real users actually upload, checked by validate_image (SYSTEM_DESIGN.md §6).
Images are generated in code, so these tests need no files and run instantly."""
from io import BytesIO

import pytest
from PIL import Image

from app.services.images import InvalidImage, validate_image


def make_image(fmt="JPEG", size=(800, 600), mode="RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, size, "white").save(buf, fmt)
    return buf.getvalue()


def rejection_message(data: bytes) -> str:
    with pytest.raises(InvalidImage) as err:
        validate_image(data)
    return str(err.value)


def test_normal_jpeg_and_png_are_accepted():
    assert validate_image(make_image("JPEG")) == "jpg"
    assert validate_image(make_image("PNG")) == "png"


def test_extension_comes_from_contents_not_filename():
    # A PNG the user named shirt.jpg is stored as .png
    png_bytes = make_image("PNG")
    assert validate_image(png_bytes) == "png"


def test_iphone_multi_picture_jpeg_is_accepted():
    # iPhone JPEGs often contain extra pictures (HDR/depth): Pillow calls them "MPO"
    buf = BytesIO()
    first, extra = Image.new("RGB", (800, 600), "white"), Image.new("RGB", (800, 600), "black")
    first.save(buf, "MPO", save_all=True, append_images=[extra])
    with Image.open(BytesIO(buf.getvalue())) as img:
        assert img.format == "MPO"           # make sure the test really builds an MPO
    assert validate_image(buf.getvalue()) == "jpg"


def test_pdf_renamed_to_jpg_is_rejected():
    fake = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n" * 20
    assert "isn't a valid image" in rejection_message(fake)


def test_empty_file_gets_clear_message():
    assert "empty" in rejection_message(b"")


def test_heic_photo_gets_clear_message():
    # Real HEIC files start with a box size, then "ftyp" + "heic"
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100
    assert "export it as JPEG" in rejection_message(heic)


def test_gif_is_rejected_with_its_format_named():
    assert "GIF images aren't supported" in rejection_message(make_image("GIF", mode="P"))


def test_half_downloaded_photo_is_rejected():
    full = make_image("JPEG", size=(1200, 900))
    assert "damaged or incomplete" in rejection_message(full[: len(full) // 2])


def test_tiny_thumbnail_is_rejected():
    assert "too small (400x400)" in rejection_message(make_image(size=(400, 400)))


def test_huge_resolution_image_is_rejected_before_decoding():
    # 9000x6000 = 54 MP. Mode "1" (1 bit per pixel) keeps the test file small.
    huge = make_image("PNG", size=(9000, 6000), mode="1")
    assert "over 50 megapixels" in rejection_message(huge)
