"""Phase 9a: farmer chat page is served and calls the right endpoints."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.api.web_routes import router  # noqa: E402


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_chat_page_is_served():
    r = _client().get("/chat")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for needle in ("চাষীবন্ধু", "/assistant/ask", "/photo/diagnose", "/photo/crops", 'data-theme'):
        assert needle in r.text
