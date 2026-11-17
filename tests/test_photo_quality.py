"""Phase 14 fix: photo quality has 3 levels; only "poor" leads to retake."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chashibondhu.assistant.vision import diagnose as dg  # noqa: E402

ALLOWED = {"late_blight", "virus", dg.HEALTHY_ID}


def _obj(quality, cands=None):
    return {"is_plant_photo": True, "image_quality": quality, "crop_matches": True,
            "candidates": cands if cands is not None
            else [{"id": "late_blight", "likelihood": "high"}]}


def test_ok_quality_is_not_retake():
    status, cands = dg.decide(_obj("ok"), ALLOWED)
    assert status == "possible"
    assert cands[0].problem_id == "late_blight"


def test_poor_quality_is_retake():
    assert dg.decide(_obj("poor"), ALLOWED) == ("retake", [])


def test_quality_word_is_normalised():
    assert dg.image_quality({"image_quality": " OK "}) == "ok"
    assert dg.image_quality({"image_quality": "Poor"}) == "poor"
    assert dg.image_quality({"image_quality": "blurry-ish"}) == "unknown"
    assert dg.image_quality({}) == "unknown"


def test_unknown_quality_is_not_retake():
    status, _ = dg.decide(_obj("medium"), ALLOWED)
    assert status == "possible"


def test_prompt_has_three_levels_and_formats():
    text = dg.SYSTEM_PROMPT.format(crop_en="potato", crop_bn="আলু",
                                   problem_lines="  - late_blight: x (y)")
    assert '"good" or "ok" or "poor"' in text
    assert "NOT poor quality" in text


def test_look_returns_image_quality(monkeypatch):
    fake_img = SimpleNamespace(jpeg=b"x", width=10, height=10)
    monkeypatch.setattr(dg, "prepare_image", lambda image: fake_img)

    class FakeVision:
        model = "fake"

        def analyze(self, system, text, jpeg):
            return ('{"is_plant_photo": true, "image_quality": "ok", "crop_matches": true,'
                    ' "visible_signs_bn": [], "candidates": []}')

    class FakeCatalogue:
        def crop(self, crop_id):
            return SimpleNamespace(name_en="potato", name_bn="আলু")

        def for_crop(self, crop_id):
            return []

    seen = dg.PhotoDiagnoser(FakeVision(), FakeCatalogue()).look("potato", b"img")
    assert seen["image_quality"] == "ok"
    assert seen["status"] == "unsure"     # no candidates -> unsure, not retake
