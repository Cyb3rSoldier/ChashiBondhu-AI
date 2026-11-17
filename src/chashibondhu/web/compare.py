"""Product comparison: only units that can really be compared; prices shown per base unit.

kg / gram / maund -> per kg      (1 maund = 40 seer = 37.3242 kg, the standard Bangladesh maund)
piece / dozen     -> per piece   (1 dozen = 12 pieces)
litre             -> per litre
packet            -> not comparable (packet size is unknown), shown on its own
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MAX_ITEMS = 4
MAUND_KG = Decimal("37.3242")
BASE = {"kg": ("kg", Decimal("1")), "gram": ("kg", Decimal("0.001")), "maund": ("kg", MAUND_KG),
        "piece": ("piece", Decimal("1")), "dozen": ("piece", Decimal("12")), "litre": ("litre", Decimal("1"))}
BASE_LABEL = {"kg": ("কেজি", "kg"), "piece": ("পিস", "piece"), "litre": ("লিটার", "litre")}


def per_base(unit: str, price) -> tuple[str | None, Decimal | None]:
    """('kg', price per kg) or (None, None) when the unit cannot be compared."""
    if unit not in BASE or price is None:
        return None, None
    base, factor = BASE[unit]
    return base, (Decimal(price) / factor).quantize(Decimal("0.01"), ROUND_HALF_UP)


def groups(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (comparable groups [{base, rows}], rows that cannot be compared). Cheapest per base unit is marked."""
    by: dict[str, list[dict]] = {}
    alone = []
    for r in rows:
        base, unit_price = per_base(r["unit"], r["price_now"])
        if base is None:
            alone.append(r)
            continue
        by.setdefault(base, []).append({**r, "base": base, "base_price": unit_price})
    out = []
    for base, items in by.items():
        items.sort(key=lambda x: x["base_price"])
        if len(items) > 1:
            low = items[0]["base_price"]
            for x in items:
                x["cheapest"] = x["base_price"] == low
        out.append({"base": base, "rows": items})
    return out, alone


def clean_ids(raw) -> list[int]:
    out = []
    for x in raw or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i > 0 and i not in out:
            out.append(i)
    return out[:MAX_ITEMS]
