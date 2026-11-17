"""Create (or reset) an admin account. The password is typed in, never put in a file.

Run:  python scripts/create_admin.py --phone 01XXXXXXXXX --name "Siyam"
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True)
    ap.add_argument("--name", default="Admin")
    args = ap.parse_args()

    from chashibondhu.web.db import execute
    from chashibondhu.web.passwords import MIN_LENGTH, hash_password
    from chashibondhu.web.phone import normalize_phone

    phone = normalize_phone(args.phone)
    if not phone:
        print("Not a valid Bangladesh mobile number.")
        return 1
    pw = getpass.getpass(f"New admin password (min {MIN_LENGTH} chars): ")
    if pw != getpass.getpass("Type it again: "):
        print("Passwords do not match.")
        return 1
    try:
        pw_hash = hash_password(pw)
    except ValueError as e:
        print(e)
        return 1
    execute("""
        INSERT INTO users (role, full_name, phone, password_hash, status)
        VALUES ('admin', %s, %s, %s, 'active')
        ON CONFLICT (phone) DO UPDATE
          SET role = 'admin', full_name = EXCLUDED.full_name, password_hash = EXCLUDED.password_hash,
              status = 'active', failed_logins = 0, locked_until = NULL
    """, (args.name, phone, pw_hash))
    print("Admin ready:", phone)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
