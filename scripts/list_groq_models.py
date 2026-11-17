"""List the Groq models YOUR API key can use (Phase 14 helper). Free: no tokens used.

Run:  python scripts/list_groq_models.py
Reads GROQ_API_KEY from .env. Prints model ids only (never the key).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from chashibondhu.assistant.llm.gemini import load_dotenv_if_present
    load_dotenv_if_present(ROOT)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("GROQ_API_KEY is not set in .env")
        return 1
    r = requests.get("https://api.groq.com/openai/v1/models", timeout=30,
                     headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        print(f"HTTP {r.status_code}")
        return 1
    models = sorted(r.json().get("data", []), key=lambda m: m.get("id", ""))
    hints = ("vision", "scout", "maverick", "qwen", "llama-4", "vl", "gemma")
    for m in models:
        mid = m.get("id", "")
        mark = "  <- maybe vision" if any(h in mid.lower() for h in hints) else ""
        print(f"{mid}  active={m.get('active')}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
