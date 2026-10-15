import io
from dataclasses import dataclass

import anyio
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import get_settings

# A 24MP photo is plenty; anything larger is a decompression bomb, not evidence.
Image.MAX_IMAGE_PIXELS = 40_000_000


class ImageRejected(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    original: bytes
    thumbnail: bytes
    width: int
    height: int
    # 64-bit difference hash, hex. Near-identical photos (a screenshot of
    # another photo, a re-upload) land within a few bits of each other.
    dhash: str = ""


def _encode(image: Image.Image, max_width: int, quality: int) -> tuple[bytes, Image.Image]:
    resized = image.copy()
    if resized.width > max_width:
        height = max(1, round(resized.height * max_width / resized.width))
        resized = resized.resize((max_width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), resized


def _process(data: bytes) -> ProcessedImage:
    settings = get_settings()
    try:
        source = Image.open(io.BytesIO(data))
        source.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageRejected("That photo could not be read. Attach a JPEG.") from exc

    if source.format != "JPEG":
        raise ImageRejected("Photos must be JPEG.")

    # Bake the orientation in before the EXIF that described it is dropped.
    oriented = ImageOps.exif_transpose(source).convert("RGB")

    # Copying the pixels into a fresh image is what guarantees nothing from the
    # upload's metadata survives: no EXIF, no GPS, no maker notes, no ICC
    # profile. The client strips EXIF too, but this is the actual guarantee.
    stripped = Image.new("RGB", oriented.size)
    stripped.paste(oriented)

    original, stored = _encode(
        stripped, settings.stored_image_width, settings.jpeg_quality
    )
    thumbnail, _ = _encode(stripped, settings.thumbnail_width, settings.jpeg_quality)
    return ProcessedImage(
        original=original,
        thumbnail=thumbnail,
        width=stored.width,
        height=stored.height,
        dhash=dhash(stripped),
    )


def dhash(image: Image.Image) -> str:
    """Difference hash: shrink to 9x8 grey and record whether each pixel is
    brighter than its right neighbour. Survives recompression, resizing and
    small crops, which is exactly what a screenshot of a photo does to it."""
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (left > right)
    return f"{bits:016x}"


def hash_distance(a: str, b: str) -> int:
    """How many of the 64 bits differ. 0 is the same picture."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


async def process_jpeg(data: bytes) -> ProcessedImage:
    settings = get_settings()
    if not data:
        raise ImageRejected("That photo was empty.")
    if len(data) > settings.max_photo_bytes:
        limit_mb = settings.max_photo_bytes // (1024 * 1024)
        raise ImageRejected(f"Each photo must be under {limit_mb} MB.")
    return await anyio.to_thread.run_sync(_process, data)
