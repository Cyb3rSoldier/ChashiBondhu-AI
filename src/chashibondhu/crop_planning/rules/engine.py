"""Rule-based crop suitability engine (Phase 4).

Principles:
  1. Only status == verified knowledge is used (crop_requirements, crop_calendar,
     seasons). A requirement that is not verified gives 'unknown', never a pass.
  2. Agricultural suitability only. Market demand is NOT used here; it may later
     re-rank crops that are already suitable, never rescue an unsuitable one.
  3. Every check returns a reason with the value, the requirement, its source
     page, and the data type of the area value.

Check logic (per check):
  outside absolute [min, max]       -> not_suitable
  outside optimum [opt_min, opt_max] -> marginal
  inside optimum                    -> suitable
  requirement or data missing       -> unknown
Crop status: not_suitable if any check fails; unknown if NEITHER the BARC
crop zoning check NOR both core checks (temperature and soil pH) could be
evaluated; marginal if any check is marginal; otherwise suitable.

Evidence priority (Phase 6, decided 2026-11-09):
  When the BARC check has a result, checks based on a GLOBAL model estimate
  (data_type in WEAK_DATA_TYPES, today SoilGrids pH and texture) can no longer
  lower the crop status. A marginal / not_suitable result from them becomes
  status "warning" (kept visible, original verdict in overridden_status).
  Reason: BARC is a local expert assessment that already used local land and
  soil data; a 250 m global estimate is weaker evidence.
  When BARC has no result, global checks still count: they are the best evidence.

BARC crop zoning check (expert land suitability, upazila level):
  >= 50% of farmland very suitable/suitable  -> suitable
  >= 80% marginally/not suitable              -> not_suitable
  otherwise                                   -> marginal (mixed area)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from chashibondhu.crop_planning.features.area_features import AreaFeatures
from chashibondhu.crop_planning.features.barc_zoning import BarcStore
from chashibondhu.reference.validate import read_reference, verified_only

STATUS_ORDER = {"suitable": 0, "marginal": 1, "unknown": 2, "not_suitable": 3}
CORE_CHECKS = {"temperature", "soil_ph"}
PLANTING = ("seedbed_sowing", "sowing", "transplanting")
BARC_GOOD_MIN = 0.50
BARC_POOR_MIN = 0.80
LAND_TYPES = {"highland", "medium_highland", "medium_lowland", "lowland", "very_lowland"}
WEAK_DATA_TYPES = {"global_model_estimate"}
NON_SCORING = {"info", "warning"}     # shown to admins, never decide the crop status


@dataclass
class CheckResult:
    check: str
    status: str
    message: str
    value: str = ""
    requirement: str = ""
    source: str = ""          # e.g. BARI_KPH p. 87
    data_type: str = ""
    overridden_status: str = ""   # set when a weak check was demoted to "warning"


@dataclass
class CropResult:
    crop_id: str
    name_en: str
    name_bn: str
    status: str
    checks: list[CheckResult] = field(default_factory=list)
    growing_months: list[int] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    evidence_coverage: float = 0.0   # share of checks that could be evaluated

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- knowledge ----------
class Knowledge:
    """Verified-only view of the Phase 3 reference files."""

    def __init__(self, ref_dir: Path):
        ref_dir = Path(ref_dir)
        self.catalogue = read_reference(ref_dir / "crop_catalogue.csv").set_index("crop_id")
        self.req = verified_only(read_reference(ref_dir / "crop_requirements.csv"))
        self.cal = verified_only(read_reference(ref_dir / "crop_calendar.csv"))
        self.seasons = verified_only(read_reference(ref_dir / "seasons.csv"))

    def requirement(self, crop: str, param: str) -> pd.Series | None | str:
        """Return the verified general requirement row, None, or 'conflict'."""
        rows = self.req[(self.req["crop_id"] == crop) & (self.req["parameter"] == param)
                        & (self.req["variety_scope"] == "general")]
        if rows.empty:
            return None
        cols = ["min", "opt_min", "opt_max", "max", "value_text"]
        if len(rows[cols].drop_duplicates()) > 1:
            return "conflict"
        return rows.iloc[0]

    def growing_months(self, crop: str) -> tuple[list[int], str]:
        """Months from earliest planting start to latest harvest end (wraps the year)."""
        c = self.cal[(self.cal["crop_id"] == crop) & (self.cal["variety_scope"] == "general")
                     & (self.cal["region_scope"] == "national")]
        plant = c[c["activity"].isin(PLANTING)]
        harvest = c[c["activity"] == "harvest"]
        if not plant.empty and not harvest.empty:
            start = min(int(m) for m in plant["start_month"])
            end = max(int(m) for m in harvest["end_month"])
            src = _src(plant.iloc[0])
            return _month_span(start, end), f"crop calendar ({src})"
        seasons = self.catalogue.loc[crop, "season_systems"].split("|")
        s = self.seasons[self.seasons["season_id"].isin(seasons)]
        if len(s) == 1:  # only safe when the crop has exactly one verified season
            r = s.iloc[0]
            return (_month_span(int(r["start_month"]), int(r["end_month"])),
                    f"season window only ({_src(r)})")
        return [], ""


def _src(row: pd.Series) -> str:
    loc = row.get("source_locator", "")
    return f"{row['source_id']} {loc}".strip()


def _month_span(start: int, end: int) -> list[int]:
    months, m = [start], start
    while m != end:
        m = m % 12 + 1
        months.append(m)
    return months


def _f(v: str) -> float | None:
    v = str(v).strip()
    return float(v) if v else None


def _range_check(value: float, req: pd.Series) -> str:
    lo, olo, ohi, hi = (_f(req[c]) for c in ("min", "opt_min", "opt_max", "max"))
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return "not_suitable"
    if (olo is not None and value < olo) or (ohi is not None and value > ohi):
        return "marginal"
    return "suitable"


def _req_text(req: pd.Series, unit: str) -> str:
    parts = []
    if req["opt_min"] or req["opt_max"]:
        parts.append(f"optimum {req['opt_min'] or '?'}-{req['opt_max'] or '?'} {unit}")
    if req["min"] or req["max"]:
        parts.append(f"limits {req['min'] or '?'}-{req['max'] or '?'} {unit}")
    return "; ".join(parts)


# ---------- engine ----------
class SuitabilityEngine:
    def __init__(self, knowledge: Knowledge, barc: BarcStore | None = None):
        self.k = knowledge
        self.barc = barc

    def evaluate(self, area: AreaFeatures, crops: list[str] | None = None,
                 land_type: str | None = None, irrigation: bool | None = None
                 ) -> list[CropResult]:
        if land_type is not None and land_type not in LAND_TYPES:
            raise ValueError(f"land_type must be one of {sorted(LAND_TYPES)}")
        crops = crops or [c for c in self.k.catalogue.index
                          if self.k.catalogue.loc[c, "initial_ml_model"] == "true"]
        unknown = [c for c in crops if c not in self.k.catalogue.index]
        if unknown:
            raise ValueError(f"unknown crop_id(s): {unknown}")
        results = [self._evaluate_crop(c, area, land_type, irrigation) for c in crops]
        return sorted(results, key=lambda r: (STATUS_ORDER[r.status], r.crop_id))

    def _evaluate_crop(self, crop: str, area: AreaFeatures, land_type: str | None,
                       irrigation: bool | None) -> CropResult:
        cat = self.k.catalogue.loc[crop]
        months, window_src = self.k.growing_months(crop)
        res = CropResult(crop, cat["name_en"], cat["name_bn"], "unknown", growing_months=months)
        res.checks = [
            self._temperature(crop, area, months, window_src),
            self._rainfall(crop, area, months, window_src, irrigation, res),
            self._ph(crop, area),
            self._texture(crop, area),
            self._land_type(crop, land_type, res),
        ]
        if self.barc is not None:
            res.checks.insert(0, self._barc_zoning(crop, area))
        self._apply_evidence_priority(res.checks)
        for flag in area.flags:
            res.checks.append(CheckResult("data_quality", "info", flag))
        evaluated = [c for c in res.checks if c.status != "info"]
        res.evidence_coverage = round(
            sum(c.status != "unknown" for c in evaluated) / len(evaluated), 2)
        statuses = {c.check: c.status for c in evaluated if c.status not in NON_SCORING}
        if "not_suitable" in statuses.values():
            res.status = "not_suitable"
        elif (statuses.get("barc_zoning", "unknown") == "unknown"
              and any(statuses.get(c, "unknown") == "unknown" for c in CORE_CHECKS)):
            res.status = "unknown"
        elif "marginal" in statuses.values():
            res.status = "marginal"
        else:
            res.status = "suitable"
        return res

    @staticmethod
    def _apply_evidence_priority(checks: list[CheckResult]) -> None:
        """Demote weak (global-model) negative checks to warnings when BARC has a result."""
        barc = next((c for c in checks if c.check == "barc_zoning"), None)
        if barc is None or barc.status == "unknown":
            return
        for c in checks:
            if c.data_type in WEAK_DATA_TYPES and c.status in ("marginal", "not_suitable"):
                c.overridden_status = c.status
                c.status = "warning"
                c.message = (f"warning only (would be {c.overridden_status}; BARC expert "
                             f"zoning takes priority over a global estimate): {c.message}")

    # ----- individual checks -----
    def _barc_zoning(self, crop, area) -> CheckResult:
        z = self.barc.get(crop, area.level, area.area_code)
        if z is None:
            return CheckResult("barc_zoning", "unknown",
                               "BARC crop zoning has no data for this crop in this area")
        if z.good >= BARC_GOOD_MIN:
            status = "suitable"
        elif z.poor >= BARC_POOR_MIN:
            status = "not_suitable"
        else:
            status = "marginal"
        scope = f" across {z.n_upazilas} upazilas" if area.level == "district" else ""
        msg = (f"{z.good:.0%} of farmland very suitable or suitable, {z.share_moderate:.0%} "
               f"moderately, {z.poor:.0%} marginally or not suitable{scope}")
        if z.note:
            msg += f" ({z.note})"
        return CheckResult("barc_zoning", status, msg, value=f"good={z.good:.2f} poor={z.poor:.2f}",
                           requirement=f"suitable if good>={BARC_GOOD_MIN:.0%}; not suitable "
                                       f"if poor>={BARC_POOR_MIN:.0%}",
                           source="BARC Crop Zoning", data_type=z.data_type)

    def _temperature(self, crop, area, months, window_src) -> CheckResult:
        dt = area.data_types.get("temperature", "")
        req = self.k.requirement(crop, "air_temp_c")
        if req is None or isinstance(req, str):
            return CheckResult("temperature", "unknown",
                               "conflicting verified sources" if req == "conflict"
                               else "no verified temperature requirement yet", data_type=dt)
        if not months:
            return CheckResult("temperature", "unknown",
                               "no verified growing calendar or season window", data_type=dt)
        worst, worst_msg = "suitable", []
        for m in months:
            t = area.t_mean.get(m)
            if t is None:
                return CheckResult("temperature", "unknown", f"no temperature for month {m}",
                                   data_type=dt)
            s = _range_check(t, req)
            if STATUS_ORDER[s] > STATUS_ORDER[worst]:
                worst = s
            if s != "suitable":
                worst_msg.append(f"month {m}: {t:.1f} C")
        vals = ", ".join(f"{m}:{area.t_mean[m]:.1f}" for m in months)
        msg = ("monthly mean temperature within optimum for all growing months"
               if worst == "suitable" else "outside range in " + "; ".join(worst_msg))
        return CheckResult("temperature", worst, msg + f" [window: {window_src}]",
                           value=f"month:degC {vals}", requirement=_req_text(req, "C"),
                           source=_src(req), data_type=dt)

    def _rainfall(self, crop, area, months, window_src, irrigation, res) -> CheckResult:
        dt = area.data_types.get("rainfall", "")
        req = self.k.requirement(crop, "season_rain_mm")
        if req is None or isinstance(req, str):
            return CheckResult("rainfall", "unknown",
                               "conflicting verified sources" if req == "conflict"
                               else "no verified seasonal rainfall requirement yet",
                               data_type=dt)
        if not months or any(m not in area.rain_mean for m in months):
            return CheckResult("rainfall", "unknown", "no growing window or rainfall data",
                               data_type=dt)
        total = sum(area.rain_mean[m] for m in months)
        p10 = sum(area.rain_p10.get(m, 0) for m in months)
        p90 = sum(area.rain_p90.get(m, 0) for m in months)
        status = _range_check(total, req)
        low = _f(req["opt_min"]) if req["opt_min"] else _f(req["min"])
        msg = f"season rain {total:.0f} mm (dry-to-wet years ~{p10:.0f}-{p90:.0f} mm)"
        if status != "suitable" and low is not None and total < low:
            regime = self.k.requirement(crop, "water_regime")
            can_irrigate = (regime is not None and not isinstance(regime, str)
                            and {"irrigated", "supplementary_irrigation"}
                            & set(regime["value_text"].split("|")))
            if can_irrigate:
                if irrigation is True:
                    status, msg = "suitable", msg + "; shortfall covered by irrigation"
                elif irrigation is None:
                    status = "marginal"
                    msg += "; needs irrigation - ask farmer"
                    res.missing_inputs.append("irrigation_available")
                else:
                    status, msg = "not_suitable", msg + "; needs irrigation, none available"
        return CheckResult("rainfall", status, msg + f" [window: {window_src}]",
                           value=f"{total:.0f} mm", requirement=_req_text(req, "mm"),
                           source=_src(req), data_type=dt)

    def _ph(self, crop, area) -> CheckResult:
        dt = area.data_types.get("soil", "")
        req = self.k.requirement(crop, "soil_ph")
        if req is None or isinstance(req, str):
            return CheckResult("soil_ph", "unknown",
                               "conflicting verified sources" if req == "conflict"
                               else "no verified pH requirement yet", data_type=dt)
        if area.ph_mean is None:
            return CheckResult("soil_ph", "unknown", "no soil pH estimate", data_type=dt)
        status = _range_check(area.ph_mean, req)
        return CheckResult("soil_ph", status,
                           f"area-average topsoil pH {area.ph_mean:.1f} (most of area "
                           f"{area.ph_p10:.1f}-{area.ph_p90:.1f}); a soil test gives "
                           f"the field value",
                           value=f"{area.ph_mean:.2f}", requirement=_req_text(req, "pH"),
                           source=_src(req), data_type=dt)

    def _texture(self, crop, area) -> CheckResult:
        dt = area.data_types.get("soil", "")
        req = self.k.requirement(crop, "soil_texture")
        if req is None or isinstance(req, str):
            return CheckResult("soil_texture", "unknown", "no verified texture requirement yet",
                               data_type=dt)
        if not area.texture:
            return CheckResult("soil_texture", "unknown", "no texture estimate", data_type=dt)
        allowed = set(req["value_text"].split("|"))
        ok = area.texture in allowed
        share = f"{area.texture_share:.0%}" if area.texture_share is not None else "?"
        return CheckResult(
            "soil_texture", "suitable" if ok else "marginal",
            f"dominant texture {area.texture} ({share} of area)"
            + ("" if ok else "; not in the recommended list - field texture may differ"),
            value=area.texture, requirement="|".join(sorted(allowed)),
            source=_src(req), data_type=dt)

    def _land_type(self, crop, land_type, res) -> CheckResult:
        req = self.k.requirement(crop, "land_type")
        if req is None or isinstance(req, str):
            return CheckResult("land_type", "unknown", "no verified land-type requirement yet")
        if land_type is None:
            res.missing_inputs.append("land_type")
            return CheckResult("land_type", "unknown",
                               "farmer's land type not given (how deep does it flood?)",
                               requirement=req["value_text"], source=_src(req))
        allowed = set(req["value_text"].split("|"))
        ok = land_type in allowed
        return CheckResult("land_type", "suitable" if ok else "not_suitable",
                           f"farmer land type {land_type}"
                           + ("" if ok else " is not recommended for this crop"),
                           value=land_type, requirement="|".join(sorted(allowed)),
                           source=_src(req), data_type="farmer_stated")


def results_to_frame(area: AreaFeatures, results: list[CropResult]) -> pd.DataFrame:
    """Flat table: one row per crop x check (for reports and QA)."""
    rows = []
    for r in results:
        for c in r.checks:
            rows.append({"area_code": area.area_code, "area_level": area.level,
                         "area_name": area.name_en, "crop_id": r.crop_id,
                         "crop_status": r.status, "evidence_coverage": r.evidence_coverage,
                         **{f"check_{k}": v for k, v in asdict(c).items()},
                         "method": "rule_based_v1",
                         "note": "historical 1991-2020 averages; not a forecast"})
    return pd.DataFrame(rows)
