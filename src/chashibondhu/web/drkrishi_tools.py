"""Dr. Krishi tools: intent detection, live weather (Open-Meteo, server side), climate history.
Every number shown to the farmer comes from these functions; the AI may only repeat them."""
from __future__ import annotations

import calendar
import csv
import re
import threading
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

import requests

from chashibondhu.web import geo_points

# ---------------------------------------------------------------- intent (no AI call, predictable)
_W = re.compile(r"আবহাওয়া|আবহাওয়া|বৃষ্টি|বৃস্টি|ঝড়|ঝড়|তাপমাত্রা|গরম|ঠান্ডা|ঠাণ্ডা|কুয়াশা|কুয়াশা|বাতাস|আর্দ্রতা|"
                r"পূর্বাভাস|সেচ কখন|কখন সেচ|স্প্রে কখন|কখন স্প্রে|abhawa|abohawa|aboha|brishti|bristi|brishti|jhor|"
                r"weather|rain|storm|forecast|temperature|wind|humid|cyclone", re.I)
_C = re.compile(r"স্বাভাবিক|সাধারণত|গড়|গড়|গত বছর|আগের বছর|ইতিহাস|জলবায়ু|বছরগুলো|normal|average|usually|last year|"
                r"climate|history|trend", re.I)
_RISK_TOPIC = re.compile(r"রোগ|পোকা|বালাই|আক্রমণ|সতর্কতা|মহামারী|disease|pest|outbreak|alert|insect|rog|poka", re.I)
_RISK_PLACE = re.compile(r"এলাকা|জেলা|উপজেলা|বর্তমানে|এখন|মৌসুম|এই সময়|এই সময়|area|district|season|now|local|region", re.I)


def intents(question: str, has_image: bool) -> list[str]:
    q = question or ""
    out = []
    if has_image:
        out.append("image")
    if _W.search(q):
        out.append("weather")
    if _C.search(q):
        out.append("climate")
    if _RISK_TOPIC.search(q) and _RISK_PLACE.search(q) and not has_image:
        out.append("risk")
    return out or ["general"]


# ---------------------------------------------------------------- live weather
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_cache: dict = {}
_lock = threading.Lock()
CACHE_SECONDS = 600


class WeatherUnavailable(Exception):
    pass


def weather(lat: float, lon: float, session=None) -> dict:
    """Current + 3 days for one point, Asia/Dhaka. Cached 10 minutes. Raises WeatherUnavailable."""
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    params = {"latitude": key[0], "longitude": key[1], "timezone": "Asia/Dhaka", "forecast_days": 3,
              "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                       "wind_speed_10m_max,wind_gusts_10m_max"}
    try:
        r = (session or requests).get(OPEN_METEO, params=params, timeout=8)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:  # noqa: BLE001
        raise WeatherUnavailable(type(e).__name__) from None
    try:
        c, d = raw["current"], raw["daily"]
        days = [{"date": d["time"][i], "t_max": d["temperature_2m_max"][i], "t_min": d["temperature_2m_min"][i],
                 "rain_mm": d["precipitation_sum"][i], "rain_prob": (d.get("precipitation_probability_max") or [None] * 3)[i],
                 "wind_max": (d.get("wind_speed_10m_max") or [None] * 3)[i],
                 "gust_max": (d.get("wind_gusts_10m_max") or [None] * 3)[i]} for i in range(len(d["time"]))]
        out = {"now": {"temp": c.get("temperature_2m"), "rh": c.get("relative_humidity_2m"),
                       "rain_mm": c.get("precipitation"), "wind": c.get("wind_speed_10m"), "time": c.get("time")},
               "days": days, "source": "Open-Meteo"}
    except (KeyError, IndexError, TypeError):
        raise WeatherUnavailable("unexpected answer") from None
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def farm_tips(w: dict) -> list[tuple[str, str]]:
    """Simple, fixed rules on the REAL forecast numbers (bn, en). Not AI."""
    tips = []
    d0 = w["days"][0] if w.get("days") else {}
    nxt = w["days"][:2]
    wet = any((x.get("rain_prob") or 0) >= 60 or (x.get("rain_mm") or 0) >= 5 for x in nxt)
    dry = all((x.get("rain_prob") or 0) < 30 and (x.get("rain_mm") or 0) < 1 for x in w.get("days", []))
    gust = max([(x.get("gust_max") or 0) for x in w.get("days", [])] or [0])
    hot = (d0.get("t_max") or 0) >= 35
    if wet:
        tips.append(("আজ-কাল বৃষ্টির সম্ভাবনা বেশি: সেচ দেওয়া ও স্প্রে করা পিছিয়ে দিন, জমিতে পানি বের হওয়ার পথ খোলা রাখুন।",
                     "Rain is likely today or tomorrow: delay irrigation and spraying, keep field drains open."))
    elif dry:
        tips.append(("সামনের দিনগুলোতে বৃষ্টির সম্ভাবনা কম: মাটি শুকনো হলে সকালে বা বিকেলে সেচ দিন।",
                      "Little rain expected: if the soil is dry, irrigate in the morning or late afternoon."))
    if gust >= 50:
        tips.append(("ঝোড়ো বাতাসের আশঙ্কা আছে: লম্বা গাছে খুঁটি দিন, পাকা ফসল তাড়াতাড়ি তোলার কথা ভাবুন।",
                     "Strong gusts possible: stake tall plants, consider harvesting ripe crops early."))
    if hot:
        tips.append(("দুপুরে বেশি গরম: দুপুরে মাঠের ভারী কাজ ও সেচ এড়িয়ে চলুন।",
                     "Very hot at midday: avoid heavy field work and irrigation at midday."))
    return tips


# ---------------------------------------------------------------- climate history (never a forecast)
def _data_dir() -> Path:
    from chashibondhu.web.db import _root
    return _root() / "data" / "processed" / "climate"


@lru_cache(maxsize=1)
def _district_normals() -> dict:
    out = {}
    try:
        with open(_data_dir() / "district_climatology_monthly.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out[(r["district_code"], int(r["month"]))] = r
    except OSError:
        pass
    return out


def climate(area_code: str, month: int | None = None) -> dict | None:
    """30-year normal (district, 1991-2020) + the 2001-2025 grid history for the nearest point, for one month."""
    p = geo_points.point(area_code)
    if not p:
        return None
    month = month or date.today().month
    days = calendar.monthrange(2001, month)[1]
    out = {"month": month, "area": {"bn": p["name_bn"], "en": p["name_en"]}, "normal": None, "recent": None}
    n = _district_normals().get((p.get("district_code") or area_code[:6], month))
    if n:
        f = lambda k: float(n[k]) if n.get(k) not in (None, "") else None  # noqa: E731
        out["normal"] = {"rain_mm": f("rain_mm_mean"), "t_mean": f("t_mean_c"), "t_max": f("t_max_c"),
                         "t_min": f("t_min_c"), "rh": f("rh_pct"), "baseline": n.get("baseline") or "1991-2020",
                         "source": "NASA POWER"}
    try:
        from chashibondhu.web.db import fetch_all
        rows = fetch_all(
            "SELECT year, t2m, t2m_max, t2m_min, precip_mm_day, rh2m FROM climate_grid_monthly "
            "WHERE month = %s AND (lat, lon) = (SELECT lat, lon FROM climate_grid_monthly "
            "ORDER BY (lat - %s) ^ 2 + (lon - %s) ^ 2 LIMIT 1) ORDER BY year", (month, p["lat"], p["lon"]))
    except Exception:  # noqa: BLE001 - table not imported yet
        rows = []
    if rows:
        rain = [(int(r["year"]), round(float(r["precip_mm_day"]) * days)) for r in rows if r["precip_mm_day"] is not None]
        if rain:
            wet = max(rain, key=lambda x: x[1])
            dry = min(rain, key=lambda x: x[1])
            last = rain[-1]
            out["recent"] = {"years": f"{rows[0]['year']}-{rows[-1]['year']}",
                             "rain_mm_avg": round(sum(v for _, v in rain) / len(rain)),
                             "wettest": {"year": wet[0], "rain_mm": wet[1]}, "driest": {"year": dry[0], "rain_mm": dry[1]},
                             "last": {"year": last[0], "rain_mm": last[1]},
                             "hottest": max(float(r["t2m_max"]) for r in rows),
                             "coldest": min(float(r["t2m_min"]) for r in rows),
                             "source": "NASA POWER (2001-2025 grid)"}
    return out if (out["normal"] or out["recent"]) else None


def numbers_of(obj) -> set[str]:
    """All numbers inside tool data, written like the guard writes them (for 'AI may only repeat these')."""
    from chashibondhu.assistant.guard import numbers_in
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            for v in {x, round(x), round(x, 1)}:
                out.update(numbers_in(str(v)))
        elif isinstance(x, str):
            out.update(numbers_in(x))
    walk(obj)
    return out
