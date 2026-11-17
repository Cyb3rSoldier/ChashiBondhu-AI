"""Turn BARC Crop Zoning .xls files into one clean table matched to our codes.

Input:  data/raw/barc_cropzoning/*.xls + manifest.csv (from fetch_barc_cropzoning.py)
        data/processed/admin/districts.csv, upazilas.csv
Output: data/processed/barc/barc_cropzoning_upazila.csv   (one row per crop x BARC upazila)
        data/interim/barc/barc_unmatched.csv              (rows a human should check)

Matching: BARC district -> our district by name similarity; then BARC upazila ->
our upazila ONLY inside that district, one-to-one (same matcher as Phase 3d).
Areas keep BARC's unit, which the files do not state (labelled unverified).

Usage:
    python scripts/build_barc_cropzoning.py
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.crop_planning.features.barc_zoning import CLASS_COLS  # noqa: E402
from chashibondhu.data_pipeline.admin.bn_names import HIGH, match_one_to_one, score  # noqa: E402

RAW = ROOT / "data" / "raw" / "barc_cropzoning"
ADMIN = ROOT / "data" / "processed" / "admin"
OUT = ROOT / "data" / "processed" / "barc" / "barc_cropzoning_upazila.csv"
REVIEW = ROOT / "data" / "interim" / "barc" / "barc_unmatched.csv"
OVERRIDES = ROOT / "data" / "reference" / "barc_upazila_overrides.csv"
OVERRIDE_COLS = ["barc_district", "barc_upazila", "upazila_code", "note",
                 "verified_by", "verified_on"]
METRO = re.compile(r"\bmetro\b", re.IGNORECASE)
SHEET = "Zone-En"
EXPECTED = ["district name", "upazila name", "very suitable", "suitable",
            "moderately suitable", "marginally suitable", "not suitable", "total area"]
DISTRICT_MIN_SCORE = 0.80
# Official renames that spelling similarity cannot catch (old BARC name -> current name).
DISTRICT_ALIASES = {"chittagong": "Chattogram", "nawabganj": "Chapai Nawabganj"}
SUM_TOLERANCE = 0.01  # class areas must add up to Total Area within 1%
SOURCE = ("BARC Land Suitability Assessment and Crop Zoning of Bangladesh "
          "(apps.barc.gov.bd/cropzoning)")
log = logging.getLogger("build_barc_cropzoning")


def read_xls(path: Path) -> pd.DataFrame:
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="calamine")
    except (ImportError, ValueError):
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="xlrd")
    raw = sheets.get(SHEET)
    if raw is None:
        log.warning("%s: no '%s' sheet, using first sheet", path.name, SHEET)
        raw = next(iter(sheets.values()))
    header = [str(h).strip().lower() for h in raw.iloc[0]]
    if header[:8] != EXPECTED or not header[8].endswith("zone"):
        raise ValueError(f"{path.name}: unexpected header {header}")
    df = raw.iloc[1:].copy()
    df.columns = ["barc_district", "barc_upazila", *CLASS_COLS, "total_area", "zone"]
    df["barc_district"] = df["barc_district"].fillna("").str.strip()
    df["barc_upazila"] = df["barc_upazila"].fillna("").str.strip()
    df = df[(df["barc_district"] != "") & (df["barc_upazila"] != "")]
    for c in [*CLASS_COLS, "total_area"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df[CLASS_COLS + ["total_area"]].isna().any(axis=1)
    if bad.any():
        log.warning("%s: %d rows with non-numeric areas dropped", path.name, int(bad.sum()))
        df = df[~bad]
    return df.reset_index(drop=True)


def load_admin() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.read_csv(ADMIN / "districts.csv", dtype=str)
    u = pd.read_csv(ADMIN / "upazilas.csv", dtype=str)
    for df, cols, name in ((d, ["district_code", "district_name"], "districts.csv"),
                           (u, ["upazila_code", "upazila_name", "district_code"],
                            "upazilas.csv")):
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"{name}: missing columns {missing}; found {list(df.columns)}")
    return d, u


def match_districts(barc_names: list[str], districts: pd.DataFrame) -> dict[str, tuple]:
    """BARC district name -> (district_code, score). Many-to-one is not allowed silently."""
    out = {}
    for name in barc_names:
        query = DISTRICT_ALIASES.get(name.strip().lower(), name)
        best = max(((score(query, r.district_name)[0], r.district_code)
                    for r in districts.itertuples()), key=lambda t: t[0])
        out[name] = (best[1], best[0]) if best[0] >= DISTRICT_MIN_SCORE else ("", best[0])
    # never let two BARC districts land on one of ours silently
    by_code: dict[str, list[str]] = {}
    for name, (code, _) in out.items():
        if code:
            by_code.setdefault(code, []).append(name)
    for code, names in by_code.items():
        if len(names) > 1:
            keep = max(names, key=lambda n: out[n][1])
            log.warning("BARC districts %s all matched %s; keeping %s", names, code, keep)
            for n in names:
                if n != keep:
                    out[n] = ("", out[n][1])
    return out


def name_variants(name: str) -> list[str]:
    """'Dighalia (Daulathpur)' -> ['Dighalia', 'Daulathpur']."""
    parts = [p.strip() for p in re.split(r"[()]", name) if p.strip()]
    return parts if len(parts) > 1 else []


def match_name_variants(df: pd.DataFrame, upazilas: pd.DataFrame) -> None:
    """Second pass for names with brackets: try each part against our still-free upazilas."""
    for dcode, grp in df[(df["upazila_code"] == "") & (df["district_code"] != "")].groupby(
            "district_code"):
        used = set(df.loc[(df["district_code"] == dcode) & (df["upazila_code"] != ""),
                          "upazila_code"])
        free = upazilas[(upazilas["district_code"] == dcode)
                        & ~upazilas["upazila_code"].isin(used)]
        for idx, row in grp.iterrows():
            best = (0.0, None)
            for v in name_variants(row["barc_upazila"]):
                for r in free.itertuples():
                    sc = score(v, r.upazila_name)[0]
                    if sc > best[0]:
                        best = (sc, r.upazila_code)
            if best[1] and best[0] >= HIGH:
                df.loc[idx, ["upazila_code", "match_method", "match_score"]] = [
                    best[1], "bracket_part", best[0]]
                free = free[free["upazila_code"] != best[1]]


def load_overrides() -> pd.DataFrame:
    if not OVERRIDES.exists():
        OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=OVERRIDE_COLS).to_csv(OVERRIDES, index=False, encoding="utf-8-sig")
        log.info("Created empty %s (add hand matches here)", OVERRIDES.name)
    ov = pd.read_csv(OVERRIDES, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in OVERRIDE_COLS if c not in ov.columns]
    if missing:
        raise ValueError(f"{OVERRIDES.name}: missing columns {missing}")
    return ov


def apply_overrides(df: pd.DataFrame, ov: pd.DataFrame, upazilas: pd.DataFrame) -> None:
    """Hand matches win. Each must point to an upazila of the same district, used once."""
    district_of = dict(zip(upazilas["upazila_code"], upazilas["district_code"]))
    for i, o in ov.iterrows():
        tag = f"{OVERRIDES.name} row {i + 2}"
        if not o["verified_by"].strip():
            raise ValueError(f"{tag}: verified_by is required")
        mask = ((df["barc_district"].str.upper() == o["barc_district"].strip().upper())
                & (df["barc_upazila"].str.lower() == o["barc_upazila"].strip().lower()))
        if not mask.any():
            continue  # this crop file may not contain it
        code = o["upazila_code"].strip()
        if code not in district_of:
            raise ValueError(f"{tag}: upazila_code '{code}' not in upazilas.csv")
        if district_of[code] != df.loc[mask, "district_code"].iloc[0]:
            raise ValueError(f"{tag}: {code} is not in the matched district")
        other = (df["upazila_code"] == code) & ~mask
        if other.any():
            raise ValueError(f"{tag}: {code} already matched to "
                             f"'{df.loc[other, 'barc_upazila'].iloc[0]}'")
        df.loc[mask, ["upazila_code", "match_method", "match_score"]] = [code, "override", 1.0]


def review_rows(out: pd.DataFrame, upazilas: pd.DataFrame) -> pd.DataFrame:
    """One row per unmatched BARC upazila (not per crop), with free candidates."""
    un = out[out["upazila_code"] == ""].drop_duplicates(["barc_district", "barc_upazila"])
    used = set(out.loc[out["upazila_code"] != "", "upazila_code"])
    rows = []
    for r in un.itertuples():
        if not r.district_code:
            reason, cands = "district not matched", ""
        elif METRO.search(r.barc_upazila):
            reason, cands = "city metro aggregate - not mapped on purpose", ""
        else:
            reason = f"{r.match_method} (score {float(r.match_score):.2f})"
            free = upazilas[(upazilas["district_code"] == r.district_code)
                            & ~upazilas["upazila_code"].isin(used)]
            cands = " ; ".join(f"{x.upazila_name}={x.upazila_code}" for x in free.itertuples())
        rows.append({"barc_district": r.barc_district, "barc_upazila": r.barc_upazila,
                     "district_code": r.district_code, "reason": reason,
                     "free_candidates_in_district": cands})
    return pd.DataFrame(rows)


def build() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    manifest_path = RAW / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{manifest_path} missing - run scripts/fetch_barc_cropzoning.py")
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    districts, upazilas = load_admin()
    overrides = load_overrides()
    frames, qc = [], {"sum_mismatch": 0}

    for m in manifest.itertuples():
        path = RAW / m.file
        if not path.exists():
            raise FileNotFoundError(f"{path} listed in manifest but missing - re-run fetch")
        df = read_xls(path)
        mism = (df[CLASS_COLS].sum(axis=1) - df["total_area"]).abs() > \
            SUM_TOLERANCE * df["total_area"].clip(lower=1)
        qc["sum_mismatch"] += int(mism.sum())

        dmap = match_districts(sorted(df["barc_district"].unique()), districts)
        df["district_code"] = df["barc_district"].map(lambda n: dmap[n][0])
        df["upazila_code"], df["match_method"], df["match_score"] = "", "none", 0.0
        for dcode, grp in df[df["district_code"] != ""].groupby("district_code"):
            ours = upazilas[upazilas["district_code"] == dcode].reset_index(drop=True)
            res = match_one_to_one(list(grp["barc_upazila"]), list(ours["upazila_name"]))
            for m_, idx in zip(res, grp.index):
                if m_.right is not None and m_.status == "draft":
                    df.loc[idx, ["upazila_code", "match_method", "match_score"]] = [
                        ours.loc[m_.right, "upazila_code"], m_.method, m_.score]
                else:
                    df.loc[idx, ["match_method", "match_score"]] = [m_.status, m_.score]
        match_name_variants(df, upazilas)
        apply_overrides(df, overrides, upazilas)
        df.insert(0, "barc_crop", m.barc_crop)
        df.insert(1, "crop_id", m.crop_id)
        df["note"] = "BARC data combines onion and garlic" if m.barc_crop == "onion_garlic" else ""
        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    out["area_unit"] = "unverified (likely ha of cultivable land)"
    out["source"] = SOURCE
    out["data_type"] = "expert_land_suitability_assessment"
    cols = ["barc_crop", "crop_id", "district_code", "upazila_code", "barc_district",
            "barc_upazila", "match_method", "match_score", *CLASS_COLS, "total_area", "zone",
            "area_unit", "note", "source", "data_type"]
    qc["our_upazilas_without_barc"] = int(
        (~upazilas["upazila_code"].isin(out.loc[out["upazila_code"] != "", "upazila_code"])).sum())
    qc["n_our_upazilas"] = len(upazilas)
    return out[cols], review_rows(out[cols], upazilas), qc


def main() -> int:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        out, review, qc = build()
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    review.to_csv(REVIEW, index=False, encoding="utf-8-sig")

    per_crop = out.groupby("barc_crop").agg(rows=("barc_upazila", "size"),
                                            matched=("upazila_code", lambda s: (s != "").sum()))
    for crop, r in per_crop.iterrows():
        log.info("%-13s %3d BARC upazilas, %3d matched to our codes", crop, r.rows, r.matched)
    log.info("BARC districts matched: %d of %d",
             out.loc[out["district_code"] != "", "barc_district"].nunique(),
             out["barc_district"].nunique())
    log.info("rows where classes do not add up to Total Area: %d", qc["sum_mismatch"])
    log.info("our upazilas with no BARC data (newer or city units): %d of %d",
             qc["our_upazilas_without_barc"], qc["n_our_upazilas"])
    methods = out.drop_duplicates(["barc_district", "barc_upazila"])["match_method"]
    log.info("match methods (unique BARC upazilas): %s", methods.value_counts().to_dict())
    log.info("unmatched BARC upazilas for review: %d (%d are city metro units) -> %s",
             len(review), int(review["reason"].str.startswith("city").sum()) if len(review) else 0,
             REVIEW.relative_to(ROOT))
    log.info("Saved %s", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
