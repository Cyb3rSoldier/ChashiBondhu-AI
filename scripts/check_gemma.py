"""Check whether GEMINI_API_KEY can use Gemma models (before building a vision fallback).

Steps: (1) list models whose name contains "gemma"; (2) send ONE tiny text request;
(3) optional: send ONE photo (metadata/GPS removed first, same as the app).
The key is read from .env and sent only in the x-goog-api-key header; it is never printed.

Usage:
  python scripts\\check_gemma.py
  python scripts\\check_gemma.py --model gemma-4-31b-it
  python scripts\\check_gemma.py --image "D:\\path\\to\\leaf.jpg"
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.assistant.llm.gemini import load_dotenv_if_present  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"
PREFERRED = ["gemma-4-31b-it"]          # tried first if the key lists it


def short_error(r: requests.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:300]
    except (ValueError, AttributeError):
        return r.text[:300]


def list_gemma(key: str) -> list[dict]:
    out, token = [], ""
    while True:
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        r = requests.get(f"{BASE}/models", params=params, timeout=30,
                         headers={"x-goog-api-key": key})
        if r.status_code != 200:
            print(f"LIST MODELS FAILED: HTTP {r.status_code}: {short_error(r)}")
            sys.exit(1)
        data = r.json()
        out += [m for m in data.get("models", []) if "gemma" in m.get("name", "").lower()]
        token = data.get("nextPageToken", "")
        if not token:
            return out


def pick_model(models: list[dict], wanted: str) -> str:
    names = [m["name"].split("/", 1)[-1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    if wanted:
        return wanted
    for p in PREFERRED:
        if p in names:
            return p
    g4 = [n for n in names if n.startswith("gemma-4")]
    return (g4 or names or [""])[0]


def generate(key: str, model: str, parts: list[dict]) -> None:
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 200}}
    r = requests.post(f"{BASE}/models/{model}:generateContent", json=body, timeout=90,
                      headers={"x-goog-api-key": key})
    if r.status_code != 200:
        print(f"  FAILED: HTTP {r.status_code}: {short_error(r)}")
        return
    try:
        cands = r.json().get("candidates", [])
        text = "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
    except (ValueError, KeyError, IndexError, TypeError):
        print("  FAILED: unexpected response shape")
        return
    print(f"  OK: {text.strip()[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="", help="model id, e.g. gemma-4-31b-it")
    ap.add_argument("--image", default="", help="optional photo path for a vision test")
    args = ap.parse_args()

    load_dotenv_if_present(ROOT)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is not set in .env")
        sys.exit(1)

    models = list_gemma(key)
    print(f"Gemma models visible to this key: {len(models)}")
    for m in models:
        methods = ",".join(m.get("supportedGenerationMethods", []))
        print(f"  {m['name'].split('/', 1)[-1]:<28} {methods}")

    model = pick_model(models, args.model)
    if not model:
        print("No Gemma model with generateContent found for this key.")
        sys.exit(1)

    print(f"\nText test with {model}:")
    generate(key, model, [{"text": "Reply with the single word: ok"}])

    if args.image:
        from chashibondhu.assistant.vision.image_prep import prepare_image
        img = Path(args.image)
        if not img.is_file():
            print(f"Image not found: {img}")
            sys.exit(1)
        prepared = prepare_image(img.read_bytes())       # metadata/GPS removed
        print(f"\nVision test with {model} ({prepared.width}x{prepared.height}):")
        generate(key, model, [
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(prepared.jpeg).decode("ascii")}},
            {"text": "In one short English sentence, what plant part is in this photo?"}])


if __name__ == "__main__":
    main()
