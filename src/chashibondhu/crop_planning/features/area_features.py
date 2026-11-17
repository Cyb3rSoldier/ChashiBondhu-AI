"""Area features for the suitability engine (district or upazila).

Reads the processed outputs of Phases 1, 2 and 2b:
  - temperature/humidity: NASA POWER 1991-2020 monthly climatology (district only)
  - rainfall:             CHIRPS v3 1991-2020 monthly climatology (district/upazila)
  - soil:                 SoilGrids 2.0 topsoil 0-30 cm (district/upazila)
Every value keeps its data_type so explanations never present a model estimate
or a 30-year average as a field measurement or a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

TEMP_FILE = "climate/district_climatology_monthly.csv"
RAIN_FILES = {"district": "climate/chirps_district_climatology.csv",
              "upazila": "climate/chirps_upazila_climatology.csv"}
SOIL_FILES = {"district": "soil/district_soil_topsoil.csv",
              "upazila": "soil/upazila_soil_topsoil.csv"}
GRID_FILE = "climate/grid_cell_sharing.csv"
LOW_SOIL_VALID = 0.5  # below this share of valid pixels, soil values are weak


@dataclass
class AreaFeatures:
    area_code: str
    level: str                      # district | upazila
    name_en: str
    district_code: str
    t_mean: dict[int, float]        # month -> deg C (district)
    rain_mean: dict[int, float]     # month -> mm
    rain_p10: dict[int, float]
    rain_p90: dict[int, float]
    ph_mean: float | None
    ph_p10: float | None
    ph_p90: float | None
    texture: str | None             # normalised: clay_loam
    texture_share: float | None
    data_types: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def _need(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}; found {list(df.columns)}")


def _monthly(df: pd.DataFrame, col: str) -> dict[int, float]:
    return {int(m): float(v) for m, v in zip(df["month"], df[col]) if pd.notna(v)}


class FeatureStore:
    """Loads all feature tables once; `get(code)` returns AreaFeatures."""

    def __init__(self, processed_dir: Path):
        self.dir = Path(processed_dir)
        self.temp = self._read(TEMP_FILE, ["district_code", "month", "t_mean_c"])
        self.rain = {lvl: self._read(f, [f"{lvl}_code", "month", "rain_mm_mean",
                                         "rain_mm_p10", "rain_mm_p90"])
                     for lvl, f in RAIN_FILES.items()}
        self.soil = {lvl: self._read(f, [f"{lvl}_code", "ph_mean", "ph_p10", "ph_p90",
                                         "texture_dominant", "texture_dominant_share",
                                         "valid_fraction"])
                     for lvl, f in SOIL_FILES.items()}
        grid_path = self.dir / GRID_FILE
        self.grid = pd.read_csv(grid_path, dtype={"district_code": str}) \
            if grid_path.exists() else None
        upz = self.soil["upazila"]
        if "district_code" not in upz.columns:
            raise ValueError(f"{SOIL_FILES['upazila']}: needs district_code column")
        self.upazila_to_district = dict(zip(upz["upazila_code"], upz["district_code"]))

    def _read(self, rel: str, cols: list[str]) -> pd.DataFrame:
        path = self.dir / rel
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run the earlier phase that builds it")
        df = pd.read_csv(path, dtype={c: str for c in ("district_code", "upazila_code")})
        _need(df, cols, rel)
        return df

    def level_of(self, code: str) -> str:
        if code in set(self.soil["upazila"]["upazila_code"]):
            return "upazila"
        if code in set(self.soil["district"]["district_code"]):
            return "district"
        raise KeyError(f"unknown area code '{code}' (not a district or upazila code)")

    def districts(self) -> list[str]:
        return sorted(self.soil["district"]["district_code"].unique())

    def get(self, code: str) -> AreaFeatures:
        level = self.level_of(code)
        district = code if level == "district" else self.upazila_to_district[code]
        flags: list[str] = []

        t = self.temp[self.temp["district_code"] == district]
        if t.empty:
            raise KeyError(f"no temperature climatology for district {district}")
        if level == "upazila":
            flags.append("temperature is the district average (no upazila temperature data)")
        if self.grid is not None:
            g = self.grid[self.grid["district_code"] == district]
            if not g.empty and int(g["n_districts_in_cell"].iloc[0]) > 1:
                flags.append(f"temperature grid cell shared by "
                             f"{int(g['n_districts_in_cell'].iloc[0])} districts (~50 km cell)")

        rain = self.rain[level]
        r = rain[rain[f"{level}_code"] == code]
        if r.empty:
            raise KeyError(f"no rainfall climatology for {level} {code}")

        soil = self.soil[level]
        s = soil[soil[f"{level}_code"] == code]
        if s.empty:
            raise KeyError(f"no soil data for {level} {code}")
        s = s.iloc[0]
        valid = float(s["valid_fraction"]) if pd.notna(s["valid_fraction"]) else 0.0
        if valid < LOW_SOIL_VALID:
            flags.append(f"soil estimate covers only {valid:.0%} of the area")
        texture = s["texture_dominant"]
        texture = None if pd.isna(texture) else str(texture).strip().lower().replace(" ", "_")

        name_col = f"{level}_name"
        name = str(s[name_col]) if name_col in s.index else code
        num = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
        return AreaFeatures(
            area_code=code, level=level, name_en=name, district_code=district,
            t_mean=_monthly(t, "t_mean_c"),
            rain_mean=_monthly(r, "rain_mm_mean"), rain_p10=_monthly(r, "rain_mm_p10"),
            rain_p90=_monthly(r, "rain_mm_p90"),
            ph_mean=num(s["ph_mean"]), ph_p10=num(s["ph_p10"]), ph_p90=num(s["ph_p90"]),
            texture=texture,
            texture_share=num(s["texture_dominant_share"]),
            data_types={
                "temperature": str(t["data_type"].iloc[0]) if "data_type" in t else "",
                "rainfall": str(r["data_type"].iloc[0]) if "data_type" in r else "",
                "soil": str(s.get("data_type", "")),
            },
            sources={
                "temperature": str(t["source"].iloc[0]) if "source" in t else "",
                "rainfall": str(r["source"].iloc[0]) if "source" in r else "",
                "soil": str(s.get("source", "")),
            },
            flags=flags,
        )
