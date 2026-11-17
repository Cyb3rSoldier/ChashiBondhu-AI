"""Developer test chat page (Phase 9a): GET /chat. The real website is in chashibondhu.web.

One self-contained HTML file (CSS + JS inside) in api/web/chat.html. It calls the existing
endpoints on the same server: POST /assistant/ask, GET /photo/crops, POST /photo/diagnose,
GET /health. Later the same page/JS moves into the PHP site (PHP calls FastAPI).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

WEB_DIR = Path(__file__).resolve().parent / "web"
CHAT_PAGE = WEB_DIR / "chat.html"

router = APIRouter(tags=["web"])


@router.get("/chat", include_in_schema=False)
def chat_page() -> FileResponse:
    if not CHAT_PAGE.is_file():
        raise HTTPException(status_code=404, detail="chat page file is missing (api/web/chat.html)")
    return FileResponse(CHAT_PAGE, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})
