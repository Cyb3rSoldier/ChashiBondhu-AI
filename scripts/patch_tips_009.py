"""One-time edit for migration 009: farmer "Tips" must show only PUBLISHED announcements (not drafts/archived).
Run from the repo root:  python scripts/patch_tips_009.py      (safe to run twice)"""
from pathlib import Path

p = Path("src/chashibondhu/web/repo.py")
s = p.read_text(encoding="utf-8")
old = "FROM announcements WHERE audience IN ('all', 'farmer') \""
new = "FROM announcements WHERE audience IN ('all', 'farmer') AND status = 'published' \""
if new in s:
    print("already patched")
elif s.count(old) == 1:
    s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")
    print("patched farmer_tips")
else:
    raise SystemExit("farmer_tips SQL not found exactly once - send this message to Claude")
