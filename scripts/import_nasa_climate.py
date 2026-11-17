r"""Import the NASA POWER monthly grid CSV into climate_grid_monthly (migration 011). Safe to run again (upsert).

  python scripts\import_nasa_climate.py data\raw\climate\Bangladesh_Climate_Master_Fixed_2001_2025.csv

Checks every row before writing: known columns, numbers, month 1-12, min <= mean <= max, rain >= 0, humidity 0-100,
point inside Bangladesh. Nothing is written if a row is bad (the bad rows are listed)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

COLS = ["YEAR", "LAT", "LON", "MO", "T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "SOLAR"]


def read_rows(path: Path) -> tuple[list[tuple], list[str]]:
    rows, bad = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        missing = [c for c in COLS if c not in (r.fieldnames or [])]
        if missing:
            raise SystemExit(f"missing columns: {missing}")
        for n, x in enumerate(r, start=2):
            try:
                v = {c: float(x[c]) for c in COLS}
            except (TypeError, ValueError):
                bad.append(f"line {n}: not a number")
                continue
            problems = []
            if not (1 <= v["MO"] <= 12) or v["MO"] != int(v["MO"]):
                problems.append("month")
            if not (20.0 <= v["LAT"] <= 27.0 and 87.5 <= v["LON"] <= 93.0):
                problems.append("point outside Bangladesh")
            if not (v["T2M_MIN"] <= v["T2M"] <= v["T2M_MAX"]):
                problems.append("min <= mean <= max")
            if v["PRECTOTCORR"] < 0 or not (0 <= v["RH2M"] <= 100) or v["SOLAR"] < 0:
                problems.append("value range")
            if problems:
                bad.append(f"line {n}: " + ", ".join(problems))
                continue
            rows.append((v["LAT"], v["LON"], int(v["YEAR"]), int(v["MO"]), v["T2M"], v["T2M_MAX"], v["T2M_MIN"],
                         v["PRECTOTCORR"], v["RH2M"], v["SOLAR"]))
    return rows, bad


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rows, bad = read_rows(Path(argv[1]))
    if bad:
        print(f"{len(bad)} bad rows, nothing imported:\n" + "\n".join(bad[:20]))
        return 1
    from chashibondhu.web.db import connect
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO climate_grid_monthly (lat, lon, year, month, t2m, t2m_max, t2m_min, precip_mm_day, rh2m, solar) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (lat, lon, year, month) DO UPDATE SET "
                "t2m = EXCLUDED.t2m, t2m_max = EXCLUDED.t2m_max, t2m_min = EXCLUDED.t2m_min, "
                "precip_mm_day = EXCLUDED.precip_mm_day, rh2m = EXCLUDED.rh2m, solar = EXCLUDED.solar", rows)
        n = conn.execute("SELECT count(*) AS n, count(DISTINCT (lat, lon)) AS pts, min(year) AS y0, max(year) AS y1 "
                         "FROM climate_grid_monthly").fetchone()
    print(f"imported {len(rows)} rows; table now has {n['n']} rows, {n['pts']} points, years {n['y0']}-{n['y1']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
