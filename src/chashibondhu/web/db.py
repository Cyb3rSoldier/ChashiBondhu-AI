"""Supabase (PostgreSQL) connection for the website.

.env (never commit):
  SUPABASE_DB_HOST=aws-0-<region>.pooler.supabase.com   (Connect -> "Session pooler")
  SUPABASE_DB_PORT=5432
  SUPABASE_DB_NAME=postgres
  SUPABASE_DB_USER=postgres.<project-ref>
  SUPABASE_DB_PASSWORD=...
  SUPABASE_DB_SSLMODE=require        (optional; "disable" only for a local test database)

Separate fields (not one URL) so a password with special characters needs no escaping.
Prepared statements are switched off, so this also works with the transaction pooler.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

REQUIRED = ("SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD")


class DatabaseNotConfigured(RuntimeError):
    """A required SUPABASE_DB_* setting is missing in .env."""


def _root() -> Path:
    env = os.environ.get("CHASHIBONDHU_ROOT", "").strip()
    return Path(env) if env else Path(__file__).resolve().parents[3]


def db_settings(root: Path | None = None) -> dict[str, Any]:
    from chashibondhu.assistant.llm.gemini import load_dotenv_if_present
    load_dotenv_if_present(root or _root())
    missing = [k for k in REQUIRED if not os.environ.get(k, "").strip()]
    if missing:
        raise DatabaseNotConfigured("missing in .env: " + ", ".join(missing))
    return {
        "host": os.environ["SUPABASE_DB_HOST"].strip(),
        "port": int(os.environ.get("SUPABASE_DB_PORT", "5432").strip() or 5432),
        "dbname": os.environ.get("SUPABASE_DB_NAME", "postgres").strip() or "postgres",
        "user": os.environ["SUPABASE_DB_USER"].strip(),
        "password": os.environ["SUPABASE_DB_PASSWORD"],
        "sslmode": os.environ.get("SUPABASE_DB_SSLMODE", "require").strip() or "require",
        "connect_timeout": 10,
        "application_name": "chashibondhu-web",
    }


def conninfo(settings: dict[str, Any]) -> str:
    from psycopg.conninfo import make_conninfo
    return make_conninfo(**settings)


@lru_cache(maxsize=1)
def get_pool():
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(
        conninfo(db_settings()),
        min_size=1, max_size=5, timeout=15, open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
    )
    pool.open(wait=True, timeout=20)
    return pool


@contextmanager
def connect() -> Iterator[Any]:
    """One pooled connection; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict]:
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: tuple | dict = ()) -> dict | None:
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict = ()) -> int:
    """INSERT / UPDATE / DELETE. Returns the number of rows changed."""
    with connect() as conn:
        return conn.execute(sql, params).rowcount
