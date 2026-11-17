"""Prepare a farmer's photo before it leaves the server (Phase 14).

* checks it is a real image (Pillow can open it) and not too big,
* applies the phone's rotation (EXIF orientation),
* re-encodes as a new JPEG -> ALL metadata is dropped, including GPS location (privacy),
* shrinks the longer side to MAX_SIDE so the base64 stays under the API limit.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024      # what the farmer may upload
MAX_SIDE = 1024                          # pixels, longer side, after shrinking
MAX_SEND_BYTES = 3 * 1024 * 1024         # base64 adds ~33%: stays under Groq's 4 MB
MIN_SIDE = 64                            # smaller is not a usable photo


class ImageError(ValueError):
    """The upload is not a usable photo (message is safe to show)."""


@dataclass(frozen=True)
class PreparedImage:
    jpeg: bytes
    width: int
    height: int
    original_format: str


def prepare_image(data: bytes) -> PreparedImage:
    if not data:
        raise ImageError("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError(f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format or "unknown"
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ImageError("not a readable image (use JPG or PNG)") from e
    if min(im.size) < MIN_SIDE:
        raise ImageError("image is too small")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.BICUBIC)
    for quality in (85, 75, 60):
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)       # new file: no EXIF / GPS
        if buf.tell() <= MAX_SEND_BYTES:
            return PreparedImage(buf.getvalue(), im.width, im.height, fmt)
    raise ImageError("image could not be made small enough")
