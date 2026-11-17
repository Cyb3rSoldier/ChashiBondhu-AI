"""Website step 1: password hashing, phone numbers, database settings (no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chashibondhu.web.db import DatabaseNotConfigured, conninfo, db_settings  # noqa: E402
from chashibondhu.web.passwords import hash_password, verify_password  # noqa: E402
from chashibondhu.web.phone import normalize_phone  # noqa: E402


def test_password_roundtrip_and_salt():
    h1, h2 = hash_password("আমার-পাস123"), hash_password("আমার-পাস123")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("আমার-পাস123", h1)
    assert not verify_password("wrong-pass", h1)
    assert not verify_password("x", "not-a-hash")


def test_password_too_short():
    with pytest.raises(ValueError):
        hash_password("123")


@pytest.mark.parametrize("raw", ["01712345678", "+8801712345678", "8801712345678",
                                 "০১৭১২৩৪৫৬৭৮", "017-1234 5678"])
def test_phone_ok(raw):
    assert normalize_phone(raw) == "+8801712345678"


@pytest.mark.parametrize("raw", ["", "0171234567", "01212345678", "abc", "+4401712345678"])
def test_phone_bad(raw):
    assert normalize_phone(raw) is None


def test_settings_missing(monkeypatch, tmp_path):
    for k in ("SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(DatabaseNotConfigured):
        db_settings(tmp_path)


def test_settings_and_conninfo_quote_password(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_DB_HOST", "aws-0-x.pooler.supabase.com")
    monkeypatch.setenv("SUPABASE_DB_USER", "postgres.abc")
    monkeypatch.setenv("SUPABASE_DB_PASSWORD", "p@ss word#1")
    monkeypatch.delenv("SUPABASE_DB_SSLMODE", raising=False)
    s = db_settings(tmp_path)
    assert s["port"] == 5432 and s["sslmode"] == "require" and s["dbname"] == "postgres"
    ci = conninfo(s)
    assert "sslmode=require" in ci and "p@ss word#1" in ci.replace("\\", "")
