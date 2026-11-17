"""Photos: check, shrink and re-save as JPEG (this also removes EXIF/GPS data).

  listings/    product photos, public at /media/listings/<file>
  avatars/     farmer profile photos, public at /media/avatars/<file>
  complaints/  complaint photos, PRIVATE (served only to the owner by a checked route)

All under data/uploads/ (git-ignored). For online hosting this can later move to Supabase Storage.
"""
from __future__ import annotations

import io
import secrets
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1600


class BadImage(ValueError):
    pass


FOLDERS = ("listings", "avatars", "complaints")


def uploads_dir(folder: str = "listings") -> Path:
    if folder not in FOLDERS:
        raise ValueError(f"unknown upload folder: {folder}")
    from chashibondhu.web.db import _root
    d = _root() / "data" / "uploads" / folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def folder_dir(folder: str) -> Path:
    """Folder for a photo kind. Product photos use plain uploads_dir() (same call as before,
    so older code and tests that replace uploads_dir() keep working)."""
    return uploads_dir() if folder == "listings" else uploads_dir(folder)


def save_listing_image(data: bytes) -> str:
    """Product photo. Returns the stored file name. Raises BadImage."""
    return save_image(data, "listings")


def save_image(data: bytes, folder: str, max_side: int = MAX_SIDE) -> str:
    """Returns the stored file name (24 hex chars + .jpg). Raises BadImage."""
    if not data:
        raise BadImage("empty file")
    if len(data) > MAX_BYTES:
        raise BadImage("photo is larger than 8 MB")
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:  # noqa: BLE001 - any decode problem means "not a usable photo"
        raise BadImage("not a valid photo") from e
    img.thumbnail((max_side, max_side))
    name = f"{secrets.token_hex(12)}.jpg"
    img.save(folder_dir(folder) / name, "JPEG", quality=85, optimize=True)   # no EXIF written
    return name
