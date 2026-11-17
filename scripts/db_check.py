"""Check the Supabase connection and that migration 001 created all tables.

Run:  python scripts/db_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXPECTED = ["ai_conversations", "ai_feedback", "ai_messages", "announcements", "cart_items",
            "contact_messages", "farm_plots", "farmer_profiles", "listings", "notifications",
            "order_items", "orders", "plantings", "reviews", "schema_migrations", "users"]


def main() -> int:
    from chashibondhu.web.db import DatabaseNotConfigured, fetch_all, fetch_one
    try:
        version = fetch_one("SELECT version() AS v")["v"]
    except DatabaseNotConfigured as e:
        print(f"NOT CONFIGURED: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - show any connection problem plainly
        print(f"CONNECTION FAILED: {type(e).__name__}: {e}")
        return 1
    print("connected:", version.split(",")[0])
    rows = fetch_all("SELECT table_name FROM information_schema.tables "
                     "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
    have = {r["table_name"] for r in rows}
    missing = [t for t in EXPECTED if t not in have]
    rls_off = [r["relname"] for r in fetch_all(
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
        "AND relkind = 'r' AND NOT relrowsecurity")]
    print(f"tables: {len(EXPECTED) - len(missing)}/{len(EXPECTED)} found")
    if missing:
        print("MISSING:", ", ".join(missing), "-> run supabase/migrations/001_init.sql in the SQL Editor")
    if rls_off:
        print("WARNING: Row Level Security is OFF for:", ", ".join(sorted(rls_off)))
    if not missing:
        mig = [r["version"] for r in fetch_all("SELECT version FROM schema_migrations ORDER BY version")]
        users = fetch_one("SELECT count(*) AS n FROM users")["n"]
        print("migrations:", ", ".join(mig), "| users:", users)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
