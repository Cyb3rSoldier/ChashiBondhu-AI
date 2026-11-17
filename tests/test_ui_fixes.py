"""UI fixes: weather uses the registered area (real coordinates), no t() inside HTML attributes, navbar labels."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TPL = ROOT / "src" / "chashibondhu" / "web" / "templates"


def test_area_point(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import geo_points, routes_geo
    (tmp_path / "districts.csv").write_text("district_code,district_name,division_code,ref_lat,ref_lon\n"
                                            "BD3026,Dhaka,BD30,23.81,90.41\n", encoding="utf-8")
    (tmp_path / "upazilas.csv").write_text("upazila_code,upazila_name,district_code,ref_lat,ref_lon\n"
                                           "BD30260024,Dohar,BD3026,23.5938,90.1414\n", encoding="utf-8")
    (tmp_path / "admin_names_bn.csv").write_text("level,pcode,parent_pcode,name_en,name_bn\n"
                                                 "upazila,BD30260024,BD3026,Dohar,দোহার\n", encoding="utf-8")
    monkeypatch.setattr(geo_points, "_admin_dir", lambda: tmp_path)
    geo_points._points.cache_clear()
    app = FastAPI()
    app.include_router(routes_geo.router)
    c = TestClient(app)
    p = c.get("/app/area-point/BD30260024").json()
    assert (p["lat"], p["lon"], p["name_bn"]) == (23.5938, 90.1414, "দোহার")
    assert c.get("/app/area-point/BD3026").json()["name_en"] == "Dhaka"
    assert c.get("/app/area-point/BD30269999").json()["code"] == "BD3026"        # unknown upazila -> its district
    assert c.get("/app/area-point/xx").status_code == 404
    assert geo_points.in_bangladesh(23.59, 90.14) and not geo_points.in_bangladesh(51.5, -0.12)
    geo_points._points.cache_clear()


def test_no_t_macro_inside_html_attributes():
    """t() returns <span> markup; inside title="..." it breaks the page (the market-card bug)."""
    bad = []
    for f in TPL.rglob("*.html"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'(title|alt|aria-label|placeholder|value)="\{\{\s*t\(', line):
                bad.append(f"{f.relative_to(TPL)}:{n}")
    assert bad == [], bad


def test_navbar_is_short():
    base = (TPL / "base.html").read_text(encoding="utf-8")
    header = base[base.index('<ul class="cb-links">'):base.index("</ul>", base.index('<ul class="cb-links">'))]
    assert 'href="#about"' not in header and 'href="#contact"' not in header and "AI সহায়তা" in header
    assert 'href="/#about"' in base and 'href="/#contact"' in base                # moved to the footer
