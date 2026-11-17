"""Tests for book extraction curation (Phase 3b)."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.curation import (  # noqa: E402
    apply_extraction, draft_rows, load_extraction, mark_verified,
)
from chashibondhu.reference.validate import read_reference, validate_all  # noqa: E402

REF = ROOT / "data" / "reference"
EXTRACTION = REF / "extractions" / "kph10_extraction.csv"


@pytest.fixture()
def ref_copy(tmp_path) -> Path:
    """Fresh Phase 3a templates in a temp folder (your real files are untouched)."""
    spec = importlib.util.spec_from_file_location(
        "tpl", ROOT / "scripts" / "make_phase3_templates.py")
    tpl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tpl)
    for name, df in tpl.build_frames().items():
        df.to_csv(tmp_path / name, index=False, encoding="utf-8-sig")
    return tmp_path


@pytest.fixture()
def extraction() -> pd.DataFrame:
    if not EXTRACTION.exists():
        pytest.skip("kph10_extraction.csv missing")
    return load_extraction(EXTRACTION)


def test_extraction_rows_are_complete(extraction):
    crops = set(read_reference(REF / "crop_catalogue.csv")["crop_id"])
    assert set(extraction["crop_id"]) <= crops
    assert (extraction["page"] != "").all() and (extraction["quote_bn"] != "").all()


def test_apply_gives_valid_draft_rows(ref_copy, extraction):
    apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    assert all(not e for e in validate_all(ref_copy).values())
    req = read_reference(ref_copy / "crop_requirements.csv")
    new = req[req["source_locator"].str.contains("KPH 10th")]
    assert len(new) > 0 and (new["status"] == "draft").all()


def test_apply_is_idempotent(ref_copy, extraction):
    apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    second = apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    assert all(c["added"] == 0 for c in second.values())


def test_verified_rows_never_overwritten(ref_copy, extraction):
    apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    name, idx, _ = draft_rows(ref_copy, "tomato")[0]
    mark_verified(ref_copy, name, idx, "tester", "2026-11-09")
    counts = apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    assert sum(c["kept_verified"] for c in counts.values()) == 1
    assert read_reference(ref_copy / name).loc[idx, "status"] == "verified"


def test_mark_verified_needs_a_name(ref_copy, extraction):
    apply_extraction(ref_copy, extraction, "BARI_KPH", "KPH 10th ed.")
    name, idx, _ = draft_rows(ref_copy)[0]
    with pytest.raises(ValueError):
        mark_verified(ref_copy, name, idx, "  ")


def test_tomato_temperature_from_book(extraction):
    """Real-world check: the book's tomato optimum is 20-25 C (KPH 10th ed. p. 142)."""
    row = extraction[(extraction["crop_id"] == "tomato") & (extraction["item"] == "air_temp_c")]
    assert row[["opt_min", "opt_max", "page"]].iloc[0].tolist() == ["20", "25", "142"]
