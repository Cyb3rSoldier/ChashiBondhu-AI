"""Curation helpers: load a book extraction into the reference files as DRAFT
rows, then let a human review each row and mark it verified.

Rules:
  - An extraction never overwrites a row that is already verified.
  - Extracted rows always enter as status=draft. Only a human review
    (mark_verified) can make them verified.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from chashibondhu.reference.validate import ENCODING, read_reference

EXTRACTION_COLS = ["target", "crop_id", "variety_scope", "item", "unit", "min", "opt_min",
                   "opt_max", "max", "value_text", "start_month", "start_day", "end_month",
                   "end_day", "region_scope", "page", "quote_bn", "note"]
REQ_FILE, CAL_FILE = "crop_requirements.csv", "crop_calendar.csv"
REQ_KEY = ["crop_id", "variety_scope", "parameter"]
CAL_KEY = ["crop_id", "variety_scope", "activity", "region_scope"]


def load_extraction(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=ENCODING)
    missing = [c for c in EXTRACTION_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    bad = df[~df["target"].isin({"requirement", "calendar"})]
    if not bad.empty:
        raise ValueError(f"{path.name}: target must be requirement or calendar "
                         f"(rows {list(bad.index + 2)})")
    no_page = df[df["page"].str.strip() == ""]
    if not no_page.empty:
        raise ValueError(f"{path.name}: every row needs a page (rows {list(no_page.index + 2)})")
    return df


def _notes(r: pd.Series) -> str:
    parts = [f"book: {r['quote_bn']}" if r["quote_bn"] else "", r["note"]]
    return " | ".join(p for p in parts if p)


def _to_requirement(r: pd.Series, source_id: str, edition: str) -> dict:
    return {"crop_id": r["crop_id"], "variety_scope": r["variety_scope"],
            "parameter": r["item"], "unit": r["unit"], "min": r["min"],
            "opt_min": r["opt_min"], "opt_max": r["opt_max"], "max": r["max"],
            "value_text": r["value_text"], "source_id": source_id,
            "source_locator": f"p. {r['page']} ({edition})", "status": "draft",
            "verified_by": "", "verified_on": "", "notes": _notes(r)}


def _to_calendar(r: pd.Series, source_id: str, edition: str) -> dict:
    return {"crop_id": r["crop_id"], "variety_scope": r["variety_scope"],
            "activity": r["item"], "start_month": r["start_month"],
            "start_day": r["start_day"], "end_month": r["end_month"],
            "end_day": r["end_day"], "region_scope": r["region_scope"] or "national",
            "source_id": source_id, "source_locator": f"p. {r['page']} ({edition})",
            "status": "draft", "verified_by": "", "verified_on": "", "notes": _notes(r)}


def _upsert(df: pd.DataFrame, new_rows: list[dict], key: list[str]) -> tuple[pd.DataFrame, dict]:
    counts = {"added": 0, "updated": 0, "kept_verified": 0}
    df = df.copy()
    for row in new_rows:
        mask = pd.Series(True, index=df.index)
        for k in key:
            mask &= df[k] == row[k]
        if mask.any():
            i = df.index[mask][0]
            if df.loc[i, "status"] == "verified":
                counts["kept_verified"] += 1
                continue
            for col, val in row.items():
                if col in df.columns:
                    df.loc[i, col] = val
            counts["updated"] += 1
        else:
            df = pd.concat([df, pd.DataFrame([{c: row.get(c, "") for c in df.columns}])],
                           ignore_index=True)
            counts["added"] += 1
    return df, counts


def apply_extraction(ref_dir: Path, extraction: pd.DataFrame, source_id: str,
                     edition: str, dry_run: bool = False) -> dict[str, dict]:
    ref_dir = Path(ref_dir)
    req = read_reference(ref_dir / REQ_FILE)
    cal = read_reference(ref_dir / CAL_FILE)
    req_rows = [_to_requirement(r, source_id, edition)
                for _, r in extraction[extraction["target"] == "requirement"].iterrows()]
    cal_rows = [_to_calendar(r, source_id, edition)
                for _, r in extraction[extraction["target"] == "calendar"].iterrows()]
    req, c1 = _upsert(req, req_rows, REQ_KEY)
    cal, c2 = _upsert(cal, cal_rows, CAL_KEY)
    if not dry_run:
        req.to_csv(ref_dir / REQ_FILE, index=False, encoding=ENCODING)
        cal.to_csv(ref_dir / CAL_FILE, index=False, encoding=ENCODING)
    return {REQ_FILE: c1, CAL_FILE: c2}


def update_source(ref_dir: Path, source_id: str, fields: dict[str, str]) -> None:
    path = Path(ref_dir) / "sources.csv"
    src = read_reference(path)
    mask = src["source_id"] == source_id
    if not mask.any():
        raise ValueError(f"source_id {source_id} not in sources.csv")
    for col, val in fields.items():
        if col in src.columns:
            src.loc[mask, col] = val
    src.to_csv(path, index=False, encoding=ENCODING)


def draft_rows(ref_dir: Path, crop: str | None = None) -> list[tuple[str, int, pd.Series]]:
    """All draft rows (file name, row index, row) for human review."""
    out = []
    for name in (REQ_FILE, CAL_FILE):
        df = read_reference(Path(ref_dir) / name)
        sel = df[(df["status"] == "draft") & ((df["crop_id"] == crop) if crop else True)]
        out += [(name, i, r) for i, r in sel.iterrows()]
    return out


def mark_verified(ref_dir: Path, file_name: str, index: int, by: str,
                  on: str | None = None) -> None:
    if not by.strip():
        raise ValueError("reviewer name is required")
    path = Path(ref_dir) / file_name
    df = read_reference(path)
    if df.loc[index, "status"] != "draft":
        raise ValueError(f"{file_name} row {index + 2} is not a draft")
    df.loc[index, ["status", "verified_by", "verified_on"]] = [
        "verified", by.strip(), on or date.today().isoformat()]
    df.to_csv(path, index=False, encoding=ENCODING)
