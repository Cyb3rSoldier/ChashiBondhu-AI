"""Plug the website into the FastAPI app.

In api/main.py (at the end):
    from chashibondhu.web.app import mount_website
    mount_website(app)

.env:  WEB_SESSION_SECRET=<long random text>   (keeps users logged in across restarts)
       WEB_COOKIE_SECURE=1                      (only when the site runs on https)
"""
from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from chashibondhu.web.deps import WEB_DIR, LoginRequired

log = logging.getLogger("chashibondhu.web")


def session_secret() -> str:
    from chashibondhu.assistant.llm.gemini import load_dotenv_if_present
    from chashibondhu.web.db import _root
    load_dotenv_if_present(_root())
    secret = os.environ.get("WEB_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        log.warning("WEB_SESSION_SECRET missing or short: using a temporary secret "
                    "(everyone is logged out when the server restarts)")
        secret = secrets.token_urlsafe(48)
    return secret


def mount_website(app: FastAPI) -> None:
    from chashibondhu.web import (routes_ai, routes_customer, routes_farmer, routes_harvest, routes_market,
                                  routes_public)

    app.add_middleware(SessionMiddleware, secret_key=session_secret(), session_cookie="cb_session",
                       max_age=14 * 24 * 3600, same_site="lax",
                       https_only=os.environ.get("WEB_COOKIE_SECURE", "") == "1")
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.include_router(routes_public.router)
    app.include_router(routes_farmer.router)
    app.include_router(routes_ai.router)
    app.include_router(routes_harvest.router)
    app.include_router(routes_market.router)
    app.include_router(routes_customer.router)
    from chashibondhu.web import routes_admin          # last: its /admin/{kind} must not hide other /admin pages
    app.include_router(routes_admin.router)

    @app.exception_handler(LoginRequired)
    async def _to_login(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _friendly_errors(request: Request, exc: StarletteHTTPException):
        """Website pages get a simple Bangla/English page for 403/404; APIs keep their JSON answer."""
        wants_html = "text/html" in request.headers.get("accept", "")
        api = request.url.path.startswith(("/app/", "/farmer/sync/", "/assistant/", "/photo/", "/areas", "/crops",
                                           "/health", "/ready", "/suitability", "/land-units", "/docs",
                                           "/market/suggest"))
        if wants_html and not api and exc.status_code in (403, 404):
            from chashibondhu.web.deps import render
            return render(request, "error.html", {"code": exc.status_code}, status_code=exc.status_code)
        return await http_exception_handler(request, exc)
