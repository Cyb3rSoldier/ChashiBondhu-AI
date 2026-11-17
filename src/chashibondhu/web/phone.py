"""Bangladesh mobile numbers: accept 01XXXXXXXXX, 8801..., +8801..., Bangla digits, spaces/dashes."""
from __future__ import annotations

import re

_BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_PATTERN = re.compile(r"^(?:\+?88)?(01[3-9]\d{8})$")


def normalize_phone(raw: str) -> str | None:
    """-> '+8801XXXXXXXXX', or None if it is not a valid BD mobile number."""
    s = re.sub(r"[\s\-()]", "", (raw or "").translate(_BN))
    m = _PATTERN.match(s)
    return "+88" + m.group(1) if m else None
