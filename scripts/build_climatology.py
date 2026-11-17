"""
build_climatology.py
--------------------
Phase 1 (ChashiBondhu AI): turn raw NASA POWER JSON into clean tables.

Outputs in data/processed/climate/:
  nasa_power_daily.parquet         one row per district per day
  nasa_power_monthly.csv           one row per district per year-month
  district_climatology_monthly.csv one row per district per calendar month
                                   (baseline period, default 1991-2020)
  grid_cell_sharing.csv            districts that fall in the same NASA POWER
                                   grid cell (they get identical values)
  qc_report.csv                    quality-check counts per district

All outputs are HISTORICAL REANALYSIS. Never present them as forecasts or as
field measurements.

Usage:
  python scripts/build_climatology.py
  python scripts/build_climatology.py --baseline-start 1991 --baseline-end 2020
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("build_climatology")

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw/climate/nasa_power/daily"
DISTRICTS_CSV = ROOT / "data/processed/admin/districts.csv"
OUT_DIR = ROOT / "data/processed/climate"

FILL_VALUE = -999.0
PARAMETERS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M"]
RENAME = {"T2M": "t_mean_c", "T2M_MAX": "t_max_c", "T2M_MIN": "t_min_c",
          "PRECTOTCORR": "rain_mm", "RH2M": "rh_pct"}

# Plausible physical ranges for Bangladesh (values outside -> flagged and set NaN)
VALID_RANGES = {"t_mean_c": (-5, 48), "t_max_c": (-5, 50), "t_min_c": (-10, 45),
                "rain_mm": (0, 1000), "rh_pct": (0, 100)}

# MERRA-2 native grid used by NASA POWER meteorology (approximate cell id)
GRID_DLAT, GRID_DLON = 0.5, 0.625

SOURCE_LABEL = "NASA POWER (MERRA-2 based), community AG"
DATA_TYPE = "historical_reanalysis"


def parse_file(path: Path) -> pd.DataFrame:
    data = json.loads(path.read_text(encoding="utf-8"))
    params = data["properties"]["parameter"]
    missing = [p for p in PARAMETERS if p not in params]
    if missing:
        raise KeyError(f"{path.name}: missing parameters {missing}")
    df = pd.DataFrame({p: pd.Series(params[p]) for p in PARAMETERS})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.rename(columns=RENAME).rename_axis("date").reset_index()
    df["district_code"] = path.stem.split("_")[0]
    return df


def quality_check(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace fill values and implausible values with NaN; return (df, qc counts)."""
    qc = {"district_code": df["district_code"].iloc[0], "n_days": len(df)}
    for col, (lo, hi) in VALID_RANGES.items():
        fill = df[col] <= FILL_VALUE + 1e-6
        out = ~fill & ((df[col] < lo) | (df[col] > hi))
        qc[f"{col}_fill"] = int(fill.sum())
        qc[f"{col}_out_of_range"] = int(out.sum())
        df.loc[fill | out, col] = np.nan
    # Consistency: min <= mean <= max (0.5 C tolerance for rounding)
    bad = (df["t_min_c"] > df["t_mean_c"] + 0.5) | (df["t_mean_c"] > df["t_max_c"] + 0.5)
    qc["t_order_violations"] = int(bad.sum())
    # Missing dates
    full = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    qc["missing_dates"] = int(len(full) - df["date"].nunique())
    return df, qc


def grid_cell(lat: float, lon: float) -> str:
    i = round((lat + 90) / GRID_DLAT)
    j = round((lon + 180) / GRID_DLON)
    return f"{i}_{j}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline-start", type=int, default=1991)
    p.add_argument("--baseline-end", type=int, default=2020)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        log.error("No JSON files in %s. Run fetch_nasa_power.py first.", RAW_DIR)
        return 1
    districts = pd.read_csv(DISTRICTS_CSV)

    frames, qc_rows = [], []
    for f in files:
        try:
            df, qc = quality_check(parse_file(f))
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            log.error("Skipping %s: %s", f.name, e)
            continue
        frames.append(df)
        qc_rows.append(qc)
    if not frames:
        log.error("No usable files.")
        return 1

    daily = pd.concat(frames, ignore_index=True)
    daily = daily.drop_duplicates(["district_code", "date"], keep="last")
    daily = daily.merge(districts[["district_code", "district_name", "division_code"]],
                        on="district_code", how="left")
    if daily["district_name"].isna().any():
        log.error("Some climate files do not match any district code.")
        return 1

    n_districts = daily["district_code"].nunique()
    if n_districts != len(districts):
        log.warning("Climate covers %d of %d districts. Re-run fetch for the rest.",
                    n_districts, len(districts))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily["source"] = SOURCE_LABEL
    daily["data_type"] = DATA_TYPE
    daily.to_parquet(OUT_DIR / "nasa_power_daily.parquet", index=False)
    pd.DataFrame(qc_rows).to_csv(OUT_DIR / "qc_report.csv", index=False)

    # ---------- Monthly (per year) ----------
    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month
    monthly = (daily.groupby(["district_code", "district_name", "year", "month"])
               .agg(t_mean_c=("t_mean_c", "mean"),
                    t_max_c=("t_max_c", "mean"),
                    t_min_c=("t_min_c", "mean"),
                    rain_mm=("rain_mm", "sum"),
                    rh_pct=("rh_pct", "mean"),
                    rain_days_valid=("rain_mm", "count"),
                    n_days=("date", "count"))
               .reset_index())
    # A month with incomplete rainfall gets NaN total instead of a too-small sum
    monthly.loc[monthly["rain_days_valid"] < monthly["n_days"], "rain_mm"] = np.nan
    monthly = monthly.round(2)
    monthly.to_csv(OUT_DIR / "nasa_power_monthly.csv", index=False)

    # ---------- Climatology (baseline period) ----------
    base = monthly[monthly["year"].between(args.baseline_start, args.baseline_end)]
    n_years = base.groupby(["district_code", "month"])["year"].nunique()
    expected_years = args.baseline_end - args.baseline_start + 1
    if (n_years < expected_years).any():
        log.warning("Some district-months have fewer than %d years in the baseline.",
                    expected_years)
    clim = (base.groupby(["district_code", "district_name", "month"])
            .agg(t_mean_c=("t_mean_c", "mean"),
                 t_max_c=("t_max_c", "mean"),
                 t_min_c=("t_min_c", "mean"),
                 rain_mm_mean=("rain_mm", "mean"),
                 rain_mm_sd=("rain_mm", "std"),
                 rain_mm_p10=("rain_mm", lambda s: s.quantile(0.10)),
                 rain_mm_p90=("rain_mm", lambda s: s.quantile(0.90)),
                 rh_pct=("rh_pct", "mean"),
                 n_years=("year", "nunique"))
            .reset_index().round(2))
    clim["baseline"] = f"{args.baseline_start}-{args.baseline_end}"
    clim["source"] = SOURCE_LABEL
    clim["data_type"] = DATA_TYPE
    clim.to_csv(OUT_DIR / "district_climatology_monthly.csv", index=False)

    # ---------- Grid-cell sharing (honesty about resolution) ----------
    d = districts[["district_code", "district_name", "ref_lat", "ref_lon"]].copy()
    d["grid_cell"] = [grid_cell(a, b) for a, b in zip(d["ref_lat"], d["ref_lon"])]
    d["n_districts_in_cell"] = d.groupby("grid_cell")["district_code"].transform("count")
    d.sort_values(["n_districts_in_cell", "grid_cell"], ascending=[False, True]) \
        .to_csv(OUT_DIR / "grid_cell_sharing.csv", index=False)
    shared = (d["n_districts_in_cell"] > 1).sum()

    qc = pd.DataFrame(qc_rows)
    flagged = qc.filter(like="out_of_range").sum().sum() + qc["t_order_violations"].sum()
    log.info("Daily rows: %d | districts: %d | years: %d-%d",
             len(daily), n_districts, daily["year"].min(), daily["year"].max())
    log.info("QC: %d fill values, %d flagged values, %d missing dates",
             int(qc.filter(like="_fill").sum().sum()), int(flagged),
             int(qc["missing_dates"].sum()))
    log.info("Climatology rows: %d (expected %d)", len(clim), n_districts * 12)
    log.info("%d districts share a NASA POWER grid cell with another district "
             "(see grid_cell_sharing.csv)", shared)
    log.info("Saved outputs to %s", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
