"""Offline smoke test for the video-incident tool (analyze_report_video).

No GCP credentials or google-genai install required: a fake google.genai module
is injected, so this validates the video_tools contract (default-off, no-video
handling, dict shape, tolerant JSON parse, never-raises) deterministically.

Usage:
    python scripts/test_video_tools_local.py
"""
import importlib
import os
import sys
import types

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agent", "src")
)


# ---------------------------------------------------------------- fake genai
class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    reply = "{}"
    raise_exc = False

    def generate_content(self, model=None, contents=None):
        if _FakeModels.raise_exc:
            raise RuntimeError("simulated Vertex outage")
        return _FakeResp(_FakeModels.reply)


class _FakeClient:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeClient.last_kwargs = kwargs
        self.models = _FakeModels()


class _FakePart:
    @staticmethod
    def from_uri(file_uri=None, mime_type=None):
        return {"file_uri": file_uri, "mime_type": mime_type}

    @staticmethod
    def from_text(text=None):
        return {"text": text}


def _install_fake_genai():
    g = sys.modules.setdefault("google", types.ModuleType("google"))
    genai = types.ModuleType("google.genai")
    genai.Client = _FakeClient
    gtypes = types.ModuleType("google.genai.types")
    gtypes.Part = _FakePart
    gtypes.HttpOptions = lambda **k: {"http": k}
    genai.types = gtypes
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.types"] = gtypes
    g.genai = genai


# ------------------------------------------------------------------- tests
def test_disabled_is_noop(vt):
    os.environ.pop("AUTOSRE_VIDEO_ENABLED", None)
    importlib.reload(vt)
    out = vt.analyze_report_video("gs://b/rec.mp4")
    ok = out["ok"] and out["enabled"] is False and "note" in out and not vt.enabled()
    return ok, f"out={out}"


def test_no_video_ref(vt):
    os.environ["AUTOSRE_VIDEO_ENABLED"] = "1"
    importlib.reload(vt)
    out = vt.analyze_report_video("")
    ok = out["ok"] and out["enabled"] is True and "note" in out
    return ok, f"out={out}"


def test_happy_path_shape(vt):
    _FakeModels.raise_exc = False
    _FakeModels.reply = (
        '{"surfaced_symptom":"ログイン後に503","reproduction_steps":["ログイン","保存を押す"],'
        '"timeline":[{"t":"0:17","event":"HTTP 503 表示"},{"t":"0:19","event":"再試行も失敗"}]}'
    )
    out = vt.analyze_report_video("gs://b/rec.mp4")
    ok = (
        out["ok"] and out["enabled"] is True
        and out["video_ref"] == "gs://b/rec.mp4"
        and out["surfaced_symptom"] == "ログイン後に503"
        and out["reproduction_steps"] == ["ログイン", "保存を押す"]
        and out["timeline"][0] == {"t": "0:17", "event": "HTTP 503 表示"}
        and "reminder" in out
    )
    return ok, f"out={out}"


def test_tolerates_code_fence(vt):
    _FakeModels.reply = '```json\n{"surfaced_symptom":"x","reproduction_steps":[],"timeline":[]}\n```'
    out = vt.analyze_report_video("gs://b/rec.mp4")
    ok = out["ok"] and out["surfaced_symptom"] == "x"
    return ok, f"out={out}"


def test_mime_from_extension(vt):
    # .mov should be detected; the fake Part records the mime we passed.
    _FakeModels.reply = '{"surfaced_symptom":"x","reproduction_steps":[],"timeline":[]}'
    vt.analyze_report_video("gs://b/rec.mov?sig=abc")
    ok = vt._mime_for("gs://b/rec.mov?sig=abc") == "video/mov" and vt._mime_for("gs://b/x.mp4") == "video/mp4"
    return ok, f"mov={vt._mime_for('a.mov')} mp4={vt._mime_for('a.mp4')} default={vt._mime_for('a.bin')}"


def test_bad_json_never_raises(vt):
    _FakeModels.reply = "not json at all"
    try:
        out = vt.analyze_report_video("gs://b/rec.mp4")
        ok = out["ok"] is False and out["enabled"] is True and "error" in out
        detail = f"out={out}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    return ok, detail


def test_api_outage_never_raises(vt):
    _FakeModels.raise_exc = True
    try:
        out = vt.analyze_report_video("gs://b/rec.mp4")
        ok = out["ok"] is False and out["enabled"] is True and "error" in out
        detail = f"out={out}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    _FakeModels.raise_exc = False
    return ok, detail


def test_caps_oversized_lists(vt):
    _FakeModels.reply = None  # build via dict below
    import json as _json

    steps = [f"s{i}" for i in range(40)]
    tl = [{"t": f"0:{i:02d}", "event": f"e{i}"} for i in range(40)]
    _FakeModels.reply = _json.dumps(
        {"surfaced_symptom": "x", "reproduction_steps": steps, "timeline": tl}
    )
    out = vt.analyze_report_video("gs://b/rec.mp4")
    ok = len(out["reproduction_steps"]) == 20 and len(out["timeline"]) == 30
    return ok, f"steps={len(out['reproduction_steps'])} timeline={len(out['timeline'])}"


def main() -> int:
    _install_fake_genai()
    # analyze_report_video reads GOOGLE_CLOUD_PROJECT when enabled; the fake
    # genai.Client ignores it, but the code path requires it to be present.
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
    from agents import video_tools as vt

    tests = [
        test_disabled_is_noop,
        test_no_video_ref,
        test_happy_path_shape,
        test_tolerates_code_fence,
        test_mime_from_extension,
        test_bad_json_never_raises,
        test_api_outage_never_raises,
        test_caps_oversized_lists,
    ]
    passed = 0
    for t in tests:
        try:
            ok, detail = t(vt)
            ok = bool(ok)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"EXCEPTION {type(e).__name__}: {e}"
        print(("PASS" if ok else "FAIL"), t.__name__, "" if ok else f"-> {detail}")
        passed += 1 if ok else 0
    print(f"{passed}/{len(tests)} pass")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
