"""Phase 14 tests: photo prep (privacy), JSON parsing, rules, problem list, diagnoser,
vision client and the API route. Offline: fake vision model, fake book assistant."""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from chashibondhu.assistant.llm.gemini import LLMError, RateLimited  # noqa: E402
from chashibondhu.assistant.vision import diagnose as dg  # noqa: E402
from chashibondhu.assistant.vision.client import VisionClient  # noqa: E402
from chashibondhu.assistant.vision.image_prep import ImageError, prepare_image  # noqa: E402
from chashibondhu.assistant.vision.problems import ProblemCatalogue  # noqa: E402

CATALOGUE = "crop_id,name_en,name_bn,status\npotato,Potato,আলু,draft\ntomato,Tomato,টমেটো,draft\n"
PROBLEMS = ("crop_id,problem_id,name_bn,name_en,search_terms_bn,kind,status,source_note\n"
            "potato,late_blight,নাবি ধ্বসা,late blight,নাবি ধ্বসা রোগ দমন,disease,draft,x\n"
            "potato,virus,ভাইরাস রোগ,virus,ভাইরাস রোগ লক্ষণ,disease,verified,x\n"
            "potato,old_row,পুরনো,old,,disease,todo,x\n")


def jpeg_bytes(size=(1600, 1200), exif=None) -> bytes:
    buf = io.BytesIO()
    im = Image.new("RGB", size, (40, 140, 40))
    im.save(buf, format="JPEG", exif=exif) if exif is not None else im.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def ref(tmp_path):
    (tmp_path / "crop_catalogue.csv").write_text(CATALOGUE, encoding="utf-8")
    (tmp_path / "crop_problems.csv").write_text(PROBLEMS, encoding="utf-8")
    return tmp_path


class FakeVision:
    model = "fake-vision"

    def __init__(self, obj):
        self.obj, self.calls = obj, []

    def analyze(self, system, text, jpeg):
        self.calls.append((system, text, len(jpeg)))
        return self.obj if isinstance(self.obj, str) else json.dumps(self.obj, ensure_ascii=False)


class FakeAssistant:
    def __init__(self):
        self.queries = []

    def ask(self, q):
        self.queries.append(q)
        return {"status": "verified", "answer": "বইয়ের উত্তর।", "llm_requests": 1,
                "sources": [{"printed_page": 29}]}


GOOD = {"is_plant_photo": True, "image_quality": "good", "retake_tip_bn": "",
        "crop_matches": True, "visible_signs_bn": ["পাতায় কালো দাগ।"],
        "candidates": [{"id": "late_blight", "likelihood": "high"},
                       {"id": "virus", "likelihood": "low"}]}


# ---------------------------------------------------------------- image prep
def test_gps_and_all_metadata_removed_and_resized():
    exif = Image.Exif()
    exif[0x8825] = {2: (23.0, 48.0, 0.0)}          # GPS IFD
    exif[0x010F] = "Apple"                          # camera maker
    p = prepare_image(jpeg_bytes(exif=exif))
    with Image.open(io.BytesIO(p.jpeg)) as out:
        assert len(out.getexif()) == 0
        assert max(out.size) <= 1024


def test_phone_rotation_applied():
    exif = Image.Exif()
    exif[0x0112] = 6                                # rotate 90
    p = prepare_image(jpeg_bytes((400, 200), exif=exif))
    assert (p.width, p.height) == (200, 400)


@pytest.mark.parametrize("data", [b"", b"not an image at all", jpeg_bytes((40, 40))])
def test_bad_uploads_rejected(data):
    with pytest.raises(ImageError):
        prepare_image(data)


# ---------------------------------------------------------------- parsing and rules
def test_parse_json_with_think_block_and_fences():
    raw = "<think>hmm {not json}</think>```json\n{\"is_plant_photo\": true}\n```"
    assert dg.parse_json_object(raw) == {"is_plant_photo": True}
    with pytest.raises(LLMError):
        dg.parse_json_object("no json here")


def test_candidates_cleaned_sorted_and_limited():
    items = [{"id": "virus", "likelihood": "low"}, {"id": "made_up", "likelihood": "high"},
             {"id": "late_blight", "likelihood": "high"}, {"id": "late_blight", "likelihood": "low"},
             {"id": "healthy", "likelihood": "maybe"}, "junk"]
    out = dg.clean_candidates(items, {"virus", "late_blight", "healthy"})
    assert [c.problem_id for c in out] == ["late_blight", "virus"]


@pytest.mark.parametrize("obj,status", [
    ({**GOOD, "is_plant_photo": False}, "not_plant"),
    ({**GOOD, "image_quality": "poor"}, "retake"),
    ({**GOOD, "crop_matches": False}, "crop_mismatch"),
    ({**GOOD, "candidates": []}, "unsure"),
    ({**GOOD, "candidates": [{"id": "virus", "likelihood": "low"}]}, "unsure"),
    ({**GOOD, "candidates": [{"id": "healthy", "likelihood": "high"}]}, "looks_healthy"),
    (GOOD, "possible"),
])
def test_decide(obj, status):
    assert dg.decide(obj, {"late_blight", "virus", "healthy"})[0] == status


def test_signs_without_numbers_or_chemicals():
    out = dg.clean_sentences(["পাতায় কালো দাগ।", "৩টি দাগ আছে।", "ছত্রাকনাশক দিন।", 7], 4)
    assert out == ["পাতায় কালো দাগ।"]


# ---------------------------------------------------------------- problem list
def test_problem_list_draft_switch(ref):
    assert {p.problem_id for p in ProblemCatalogue.load(ref, allow_draft=True).for_crop("potato")} \
        == {"late_blight", "virus"}
    assert [p.problem_id for p in ProblemCatalogue.load(ref, allow_draft=False).for_crop("potato")] \
        == ["virus"]
    assert ProblemCatalogue.load(ref).for_crop("tomato") == []


@pytest.mark.parametrize("bad_row", [
    "maize,x,ক,x,,disease,draft,x\n",                       # crop not in catalogue
    "potato,healthy,সুস্থ,healthy,,other,draft,x\n",          # built-in id
    "potato,virus,ভাইরাস,virus,,disease,draft,x\n",           # duplicate
    "potato,y,য,y,,disease,maybe,x\n",                       # bad status
])
def test_problem_list_validation(ref, bad_row):
    (ref / "crop_problems.csv").write_text(PROBLEMS + bad_row, encoding="utf-8")
    with pytest.raises(ValueError):
        ProblemCatalogue.load(ref)


# ---------------------------------------------------------------- diagnoser
def test_possible_problem_gets_book_answer(ref):
    vision, book = FakeVision(GOOD), FakeAssistant()
    d = dg.PhotoDiagnoser(vision, ProblemCatalogue.load(ref), book)
    r = d.diagnose("potato", jpeg_bytes(), note="গত সপ্তাহে বৃষ্টি হয়েছে")
    assert r["status"] == "possible" and r["llm_requests"] == 2
    assert book.queries == ["আলু নাবি ধ্বসা রোগ দমন"]
    assert "নাবি ধ্বসা হতে পারে (সম্ভাবনা: বেশি)" in r["message_bn"]
    assert "বইয়ের উত্তর।" in r["message_bn"] and dg.OFFICE_BN in r["message_bn"]
    assert "১." in r["message_bn"]
    assert any("draft" in n for n in r["notes"])
    system, text, _ = vision.calls[0]
    assert "late_blight: নাবি ধ্বসা" in system and "old_row" not in system
    assert "বৃষ্টি" in text and r["image"]["metadata_removed"] is True


def test_unsure_does_not_call_book(ref):
    book = FakeAssistant()
    d = dg.PhotoDiagnoser(FakeVision({**GOOD, "candidates": []}), ProblemCatalogue.load(ref), book)
    r = d.diagnose("potato", jpeg_bytes())
    assert r["status"] == "unsure" and book.queries == []
    assert dg.MSG["unsure"] in r["message_bn"] and dg.OFFICE_BN in r["message_bn"]


def test_retake_message_has_tip(ref):
    obj = {**GOOD, "image_quality": "poor", "retake_tip_bn": "পাতার কাছ থেকে ছবি তুলুন।"}
    r = dg.PhotoDiagnoser(FakeVision(obj), ProblemCatalogue.load(ref)).diagnose("potato", jpeg_bytes())
    assert r["status"] == "retake" and "পাতার কাছ থেকে" in r["message_bn"]


def test_crop_without_list_and_unknown_crop(ref):
    r = dg.PhotoDiagnoser(FakeVision({**GOOD, "candidates": []}),
                          ProblemCatalogue.load(ref)).diagnose("tomato", jpeg_bytes())
    assert r["status"] == "unsure" and any("No problem list" in n for n in r["notes"])
    with pytest.raises(KeyError):
        dg.PhotoDiagnoser(FakeVision(GOOD), ProblemCatalogue.load(ref)).diagnose("rice", jpeg_bytes())


# ---------------------------------------------------------------- vision client
class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.bodies = list(responses), []

    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(json)
        return self.responses.pop(0)


def test_client_retries_without_json_mode_and_hides_key():
    ok = FakeResp(200, {"choices": [{"message": {"content": "{\"a\": 1}"}}]})
    s = FakeSession([FakeResp(400, {"error": {"message": "response_format not supported"}}), ok])
    c = VisionClient("SECRET-KEY", "m", session=s)
    assert c.analyze("sys", "txt", b"abc") == "{\"a\": 1}"
    assert "response_format" in s.bodies[0] and "response_format" not in s.bodies[1]
    with pytest.raises(RateLimited):
        VisionClient("k", "m", session=FakeSession([FakeResp(429, {})])).analyze("s", "t", b"x")
    with pytest.raises(LLMError) as e:
        VisionClient("SECRET-KEY", "m", session=FakeSession([FakeResp(500, {})])).analyze("s", "t", b"x")
    assert "SECRET-KEY" not in str(e.value)


# ---------------------------------------------------------------- eval label mapping
def test_eval_folder_mapping():
    from eval_vision_potato import true_label
    assert true_label("Viral PVY") == "virus" and true_label("Fungal Late Blight") == "late_blight"
    assert true_label("Healthy") == "healthy" and true_label("Bacterial Soft Rot") == "soft_rot"
    assert true_label("Something else") is None


# ---------------------------------------------------------------- API route
def test_route_with_fake_diagnoser(ref):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from chashibondhu.api import photo_routes
    except (ImportError, RuntimeError) as e:          # python-multipart missing
        pytest.skip(f"route deps missing: {e}")
    app = FastAPI()
    app.include_router(photo_routes.router)
    diag = dg.PhotoDiagnoser(FakeVision(GOOD), ProblemCatalogue.load(ref), FakeAssistant())
    app.dependency_overrides[photo_routes.get_diagnoser] = lambda: diag
    client = TestClient(app)
    r = client.post("/photo/diagnose", data={"crop_id": "potato"},
                    files={"image": ("leaf.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["status"] == "possible"
    assert client.post("/photo/diagnose", data={"crop_id": "potato"},
                       files={"image": ("x.jpg", b"garbage", "image/jpeg")}).status_code == 422
    assert client.post("/photo/diagnose", data={"crop_id": "rice"},
                       files={"image": ("leaf.jpg", jpeg_bytes(), "image/jpeg")}).status_code == 422
    crops = client.get("/photo/crops").json()
    assert {c["crop_id"]: c["n_problems"] for c in crops} == {"potato": 2, "tomato": 0}
