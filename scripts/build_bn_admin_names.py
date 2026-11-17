"""Attach Bangla names to our COD-AB divisions, districts and upazilas.

Matching:
  - divisions: name matching (8 areas)
  - districts: the source's DC-office point is placed inside our district
    polygons (point-in-polygon), then the names are compared as a check
  - upazilas:  name matching only INSIDE the matched district, one-to-one
Manual fixes in data/reference/admin_name_overrides.csv always win.

Usage:
    python scripts/build_bn_admin_names.py

Inputs:
    data/processed/admin/{divisions,districts,upazilas}.csv, admin_boundaries.gpkg
    data/raw/admin_bn/nuhil/*.json  (from fetch_bn_admin_names.py)
    data/reference/admin_name_overrides.csv  (optional, hand-curated)
Outputs:
    data/processed/admin/admin_names_bn.csv
    data/interim/admin/admin_bn_review.csv   (rows a human must check)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.data_pipeline.admin.bn_names import (  # noqa: E402
    has_bengali, match_one_to_one, score, top_candidates,
)

ADMIN_DIR = ROOT / "data" / "processed" / "admin"
RAW_DIR = ROOT / "data" / "raw" / "admin_bn" / "nuhil"
REF_DIR = ROOT / "data" / "reference"
OVERRIDES = REF_DIR / "admin_name_overrides.csv"
OUT_FILE = ADMIN_DIR / "admin_names_bn.csv"
REVIEW_FILE = ROOT / "data" / "interim" / "admin" / "admin_bn_review.csv"
ENC = "utf-8-sig"

LEVELS = {  # level: (file, pcode options, name options, parent options)
    "division": ("divisions.csv", ["division_code", "adm1_pcode"],
                 ["division_name", "adm1_name"], None),
    "district": ("districts.csv", ["district_code", "adm2_pcode"],
                 ["district_name", "adm2_name"], ["division_code", "adm1_pcode"]),
    "upazila": ("upazilas.csv", ["upazila_code", "adm3_pcode"],
                ["upazila_name", "adm3_name"], ["district_code", "adm2_pcode"]),
}
DISTRICT_CODE_COLS = ["district_code", "adm2_pcode"]
UPAZILA_CODE_COLS = {"upazila_code", "adm3_pcode"}
OVERRIDE_COLS = ["level", "pcode", "name_bn", "aliases_bn", "source_id",
                 "source_locator", "status", "verified_by", "verified_on", "notes"]
NEW_SOURCES = [
    {"source_id": "NUHIL_GEOCODE", "title": "bangladesh-geocode",
     "publisher": "nuhil (GitHub community dataset)", "edition_or_version": "see manifest commit",
     "url": "https://github.com/nuhil/bangladesh-geocode", "language": "bn|en",
     "source_type": "community_dataset", "license_note": "MIT",
     "accessed_on": "", "notes": "Spellings from bangladesh.gov.bd, Wikipedia, Google Maps"},
    {"source_id": "BD_NATIONAL_PORTAL", "title": "Bangladesh National Portal",
     "publisher": "Government of Bangladesh", "edition_or_version": "",
     "url": "https://bangladesh.gov.bd", "language": "bn|en",
     "source_type": "government_portal", "license_note": "FILL",
     "accessed_on": "", "notes": "Use to verify Bangla spellings of districts/upazilas"},
]
log = logging.getLogger("build_bn_admin_names")


# ---------- loading ----------
def _pick(df: pd.DataFrame, options: list[str], fname: str) -> str:
    for col in options:
        if col in df.columns:
            return col
    raise ValueError(f"{fname}: none of {options} found; columns are {list(df.columns)}")


def load_admin() -> dict[str, pd.DataFrame]:
    out = {}
    for level, (fname, pcs, nms, parents) in LEVELS.items():
        path = ADMIN_DIR / fname
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run scripts/build_admin_reference.py")
        df = pd.read_csv(path, dtype=str)
        ren = {_pick(df, pcs, fname): "pcode", _pick(df, nms, fname): "name_en"}
        if parents:
            ren[_pick(df, parents, fname)] = "parent_pcode"
        out[level] = df[list(ren)].rename(columns=ren)
    return out


def load_nuhil(name: str) -> pd.DataFrame:
    path = RAW_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run scripts/fetch_bn_admin_names.py")
    blocks = json.loads(path.read_text(encoding="utf-8"))
    tables = [b for b in blocks if isinstance(b, dict) and b.get("type") == "table"]
    if not tables or not tables[0].get("data"):
        raise ValueError(f"{path}: unexpected JSON layout (no table data)")
    df = pd.DataFrame(tables[0]["data"])
    for col in ("id", "name", "bn_name"):
        if col not in df.columns:
            raise ValueError(f"{path}: missing field '{col}'")
    return df


def find_district_layer(gpkg: Path):
    import geopandas as gpd
    try:
        layers = list(gpd.list_layers(gpkg)["name"])
    except AttributeError:  # older geopandas
        import fiona
        layers = fiona.listlayers(gpkg)
    for layer in layers:
        head = gpd.read_file(gpkg, layer=layer, rows=1)
        col = next((c for c in DISTRICT_CODE_COLS if c in head.columns), None)
        if col and not (UPAZILA_CODE_COLS & set(head.columns)):
            return (gpd.read_file(gpkg, layer=layer)[[col, "geometry"]]
                    .rename(columns={col: "adm2_pcode"}))
    raise ValueError(f"{gpkg}: no layer with adm2_pcode (district polygons)")


# ---------- matching ----------
def match_divisions(adm: pd.DataFrame, src: pd.DataFrame,
                    dist: pd.DataFrame, dist_src: pd.DataFrame) -> pd.DataFrame:
    """Use matched districts: each of our divisions takes the source division
    that most of its districts belong to (spelling-independent). Name
    similarity is kept as a check."""
    div_of = dict(zip(dist_src["id"].astype(str), dist_src["division_id"].astype(str)))
    dist = dist[dist["status"] != "missing"].copy()
    dist["src_div"] = dist["source_id_value"].map(div_of)
    src = src.assign(id=src["id"].astype(str)).set_index("id")
    rows = []
    for _, a in adm.iterrows():
        votes = dist.loc[dist["parent_pcode"] == a["pcode"], "src_div"].value_counts()
        if votes.empty or votes.index[0] not in src.index:
            rows.append(_row(a, None, 0.0, "none", "missing"))
            continue
        r = src.loc[votes.index[0]]
        obj = _Obj(r.rename(None))
        obj.id = votes.index[0]
        agree = votes.iloc[0] / votes.sum()
        s, _ = score(a["name_en"], r["name"])
        status = "draft" if agree == 1.0 else "needs_review"
        rows.append(_row(a, obj, s, "via_districts", status))
    return pd.DataFrame(rows)


def match_districts(adm: pd.DataFrame, src: pd.DataFrame) -> pd.DataFrame:
    """Point-in-polygon with DC-office points; name similarity as a check."""
    gpkg = ADMIN_DIR / "admin_boundaries.gpkg"
    try:
        import geopandas as gpd
        polys = find_district_layer(gpkg).to_crs("EPSG:4326")
        pts = gpd.GeoDataFrame(
            src, geometry=gpd.points_from_xy(src["lon"].astype(float), src["lat"].astype(float)),
            crs="EPSG:4326")
        joined = gpd.sjoin(pts, polys, how="left", predicate="within")
    except Exception as exc:  # noqa: BLE001
        log.warning("Point-in-polygon failed (%s); falling back to name matching", exc)
        return _attach(adm, src, match_one_to_one(list(adm["name_en"]), list(src["name"])))

    rows = []
    hits = joined.dropna(subset=["adm2_pcode"]).groupby("adm2_pcode")
    for _, a in adm.iterrows():
        if a["pcode"] not in hits.groups:
            rows.append(_row(a, None, 0.0, "none", "missing"))
            continue
        cand = hits.get_group(a["pcode"])
        if len(cand) > 1:  # two source districts inside one polygon
            best = max(cand.itertuples(), key=lambda r: score(a["name_en"], r.name)[0])
            rows.append(_row(a, best, score(a["name_en"], best.name)[0],
                             "point_in_polygon", "needs_review"))
            continue
        r = next(cand.itertuples())
        s, _ = score(a["name_en"], r.name)
        status = "draft" if s >= 0.6 else "needs_review"  # point is strong evidence
        rows.append(_row(a, r, s, "point_in_polygon", status))
    return pd.DataFrame(rows)


def match_upazilas(adm: pd.DataFrame, src: pd.DataFrame,
                   district_map: dict[str, str]) -> tuple[pd.DataFrame, list[dict]]:
    """district_map: source district id -> our adm2_pcode."""
    src = src.assign(adm2_pcode=src["district_id"].map(district_map))
    rows, review = [], []
    for pcode, group in adm.groupby("parent_pcode", sort=True):
        options = src[src["adm2_pcode"] == pcode].reset_index(drop=True)
        res = match_one_to_one(list(group["name_en"]), list(options["name"]))
        part = _attach(group.reset_index(drop=True), options, res)
        rows.append(part)
        for m, (_, a) in zip(res, group.reset_index(drop=True).iterrows()):
            if m.status != "draft":
                cands = top_candidates(a["name_en"], list(options["name"]))
                review.append({
                    "level": "upazila", "pcode": a["pcode"], "name_en": a["name_en"],
                    "district_pcode": pcode, "status": m.status,
                    "candidates": " ; ".join(
                        f"{options.loc[j, 'name']}={options.loc[j, 'bn_name']} ({s:.2f})"
                        for j, s in cands) or "(no source upazilas in this district)",
                })
    return pd.concat(rows, ignore_index=True), review


def _row(a: pd.Series, r, s: float, method: str, status: str) -> dict:
    return {**a.to_dict(),
            "name_bn": getattr(r, "bn_name", "") if r is not None else "",
            "source_name_en": getattr(r, "name", "") if r is not None else "",
            "source_id_value": str(getattr(r, "id", "")) if r is not None else "",
            "match_score": round(s, 3), "match_method": method, "status": status}


def _attach(adm: pd.DataFrame, src: pd.DataFrame, res) -> pd.DataFrame:
    rows = []
    for m, (_, a) in zip(res, adm.iterrows()):
        r = src.iloc[m.right] if m.right is not None else None
        rows.append(_row(a, None if r is None else _Obj(r), m.score, m.method, m.status))
    return pd.DataFrame(rows)


class _Obj:  # small adapter so Series and itertuples rows look the same
    def __init__(self, s: pd.Series):
        self.__dict__.update(s.to_dict())


# ---------- overrides and sources ----------
def ensure_overrides_file() -> pd.DataFrame:
    if not OVERRIDES.exists():
        pd.DataFrame(columns=OVERRIDE_COLS).to_csv(OVERRIDES, index=False, encoding=ENC)
        log.info("Created empty %s (add manual fixes here)", OVERRIDES.name)
    df = pd.read_csv(OVERRIDES, dtype=str, keep_default_na=False, encoding=ENC)
    missing = [c for c in OVERRIDE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{OVERRIDES.name}: missing columns {missing}")
    return df


def ensure_sources() -> set[str]:
    path = REF_DIR / "sources.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run scripts/make_phase3_templates.py")
    src = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=ENC)
    add = [s for s in NEW_SOURCES if s["source_id"] not in set(src["source_id"])]
    if add:
        src = pd.concat([src, pd.DataFrame(add)], ignore_index=True).fillna("")
        src.to_csv(path, index=False, encoding=ENC)
        log.info("Added %d source(s) to sources.csv: %s", len(add),
                 [s["source_id"] for s in add])
    return set(src["source_id"])


def apply_overrides(out: pd.DataFrame, ov: pd.DataFrame, source_ids: set[str]) -> pd.DataFrame:
    out = out.copy()
    for i, r in ov.iterrows():
        tag = f"{OVERRIDES.name} row {i + 2}"
        if r["status"] not in {"draft", "verified"}:
            raise ValueError(f"{tag}: status must be draft or verified")
        if r["source_id"] not in source_ids:
            raise ValueError(f"{tag}: source_id '{r['source_id']}' not in sources.csv")
        if r["name_bn"] and not has_bengali(r["name_bn"]):
            raise ValueError(f"{tag}: name_bn has no Bengali text (encoding damaged?)")
        if r["status"] == "verified" and not (r["source_locator"] and r["verified_by"]
                                              and r["verified_on"]):
            raise ValueError(f"{tag}: verified rows need source_locator, verified_by, verified_on")
        mask = (out["level"] == r["level"]) & (out["pcode"] == r["pcode"])
        if not mask.any():
            raise ValueError(f"{tag}: no {r['level']} with pcode {r['pcode']}")
        if r["name_bn"]:
            out.loc[mask, "name_bn"] = r["name_bn"]
        out.loc[mask, ["aliases_bn", "match_method", "status", "source", "data_type"]] = [
            r["aliases_bn"], "override", r["status"], r["source_id"], "manual_curated"]
    return out


# ---------- main ----------
def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    adm = load_admin()
    div_src, dist_src, upz_src = (load_nuhil(n) for n in ("divisions", "districts", "upazilas"))
    commit = "unknown"
    manifest = RAW_DIR / "manifest.csv"
    if manifest.exists():
        commit = str(pd.read_csv(manifest)["commit"].iloc[-1])[:12]

    dist = match_districts(adm["district"], dist_src).assign(level="district")
    div = match_divisions(adm["division"], div_src, dist, dist_src).assign(level="division")
    district_map = {row.source_id_value: row.pcode for row in dist.itertuples()
                    if row.source_id_value and row.status != "missing"}
    upz, review = match_upazilas(adm["upazila"], upz_src, district_map)
    upz = upz.assign(level="upazila")

    for frame, level in ((div, "division"), (dist, "district")):
        for r in frame[frame["status"] != "draft"].itertuples():
            review.append({"level": level, "pcode": r.pcode, "name_en": r.name_en,
                           "district_pcode": "", "status": r.status,
                           "candidates": f"{r.source_name_en}={r.name_bn} ({r.match_score:.2f})"})

    out = pd.concat([div, dist, upz], ignore_index=True)
    out["parent_pcode"] = out.get("parent_pcode", "").fillna("")
    out["aliases_bn"] = ""
    out["source"] = f"NUHIL_GEOCODE@{commit}"
    out["data_type"] = "community_dataset"
    out.loc[out["status"] == "missing", ["source", "data_type"]] = ["", "none"]
    out = out.rename(columns={"source_name_en": "alt_name_en"})

    source_ids = ensure_sources()
    out = apply_overrides(out, ensure_overrides_file(), source_ids)
    cols = ["level", "pcode", "parent_pcode", "name_en", "name_bn", "aliases_bn",
            "alt_name_en", "match_method", "match_score", "status", "source", "data_type"]
    review_df = pd.DataFrame(review, columns=["level", "pcode", "name_en", "district_pcode",
                                              "status", "candidates"])
    overridden = set(out.loc[out["match_method"] == "override", "pcode"])
    review_df = review_df[~review_df["pcode"].isin(overridden)]
    return out[cols], review_df


def main() -> int:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        out, review = build()
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False, encoding=ENC)
    review.to_csv(REVIEW_FILE, index=False, encoding=ENC)

    for level in ("division", "district", "upazila"):
        sub = out[out["level"] == level]
        counts = sub["status"].value_counts().to_dict()
        log.info("%-9s %3d areas | with Bangla name: %3d | status %s", level, len(sub),
                 int((sub["name_bn"] != "").sum()), counts)
    dist = out[out["level"] == "district"]
    log.info("districts matched by point-in-polygon: %d of %d",
             int((dist["match_method"] == "point_in_polygon").sum()), len(dist))
    log.info("rows needing human review: %d -> %s", len(review), REVIEW_FILE.relative_to(ROOT))
    log.info("Saved %s", OUT_FILE.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
