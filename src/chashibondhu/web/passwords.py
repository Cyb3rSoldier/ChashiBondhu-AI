"""Password hashing with Python's built-in scrypt (no extra package needed).

Stored format: scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2 ** 14, 8, 1, 32
MIN_LENGTH = 6          # farmers may use a short PIN-like password; lockout limits guessing


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"password must have at least {MIN_LENGTH} characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=DKLEN)
    return f"scrypt${N}${R}${P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)
