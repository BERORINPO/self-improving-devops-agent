"""AutoSRE video-incident tool — Gemini native video understanding.

analyze_report_video() watches a user-attached screen recording (a gs:// URI)
and extracts the reproduction steps and a timestamped timeline of the reported
symptom (e.g. "0:17 → the UI shows HTTP 503"). This is symptom evidence, in the
same layer as the user reports and logs — never the cause. The ReAct agent must
still confirm the root cause in the live logs/config before concluding, and a
PR can never be opened from the video alone.

Why this needs Gemini specifically: native video understanding (frame sampling +
MM:SS timestamp references, no pre-transcription pipeline) is, as of 2026-07,
effectively unique to Gemini. The tool passes the video straight through to
Vertex AI as a Part — the same genai.Client path already proven by
server._gemini_smoke — so there is no extra dependency and no frame-extraction
glue.

Default-off contract (matches every other AUTOSRE_* capability):
  AUTOSRE_VIDEO_ENABLED  unset/empty -> disabled: the tool is a no-op that
                         reports enabled=false, so the agent just proceeds with
                         logs/config. Deploys never break.
"""
import json
import os

MODEL = os.environ.get("AUTOSRE_VIDEO_MODEL", "gemini-2.5-flash")
# One call must never hang a live incident run; cap it and degrade on timeout.
_CALL_TIMEOUT_MS = 90_000

_EXT_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/mov",
    ".webm": "video/webm",
    ".avi": "video/avi",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpg",
    ".wmv": "video/wmv",
    ".3gpp": "video/3gpp",
    ".3gp": "video/3gpp",
}

_PROMPT = (
    "You are AutoSRE analyzing a screen recording that a user attached to a bug "
    "report. Watch the video and report ONLY what is visually observable — the "
    "reproduction steps the user performed and WHEN the failure becomes visible. "
    "This is the SYMPTOM, never the root cause; do not speculate about backend "
    "causes.\n"
    "Output ONLY a JSON object (no prose, no markdown, no code fences) with exactly:\n"
    '  "surfaced_symptom": string (one line, in Japanese, what the user visibly hit),\n'
    '  "reproduction_steps": array of strings (each an observed user action, in Japanese),\n'
    '  "timeline": array of objects {"t": "M:SS", "event": string in Japanese}\n'
    "    (timestamps of notable moments, e.g. when an error/HTTP code appears on screen).\n"
    "Output JSON only."
)


def enabled() -> bool:
    return bool(os.environ.get("AUTOSRE_VIDEO_ENABLED", ""))


def _log(level: str, event: str, **fields) -> None:
    print(json.dumps({"severity": level, "event": event, **fields}), flush=True)


def _mime_for(video_ref: str) -> str:
    lower = video_ref.lower().split("?")[0]
    for ext, mime in _EXT_MIME.items():
        if lower.endswith(ext):
            return mime
    return "video/mp4"


def _parse_json(text: str) -> dict:
    """Tolerantly extract the model's JSON (it sometimes wraps it in code fences)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t[3:]
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        t = t[start : end + 1]
    return json.loads(t)


def analyze_report_video(video_ref: str) -> dict:
    """Watch a user-attached screen recording and extract the reproduction steps
    and a timestamped timeline of the reported symptom.

    Use this right after reading the user reports, when a report includes a screen
    recording. The result is SYMPTOM evidence (what the user did and when the
    failure appears on screen), never the cause — you must still confirm the root
    cause in the live logs and config, and never open a PR based on the video alone.

    Args:
        video_ref: a gs:// URI of the report video, e.g. "gs://bucket/rec.mp4".
    """
    if not enabled():
        return {
            "ok": True,
            "enabled": False,
            "note": "video analysis not configured (AUTOSRE_VIDEO_ENABLED unset); "
            "proceed with the logs/config evidence",
        }
    if not video_ref or not video_ref.strip():
        return {"ok": True, "enabled": True, "note": "no video attached to this report"}
    try:
        from google import genai  # lazy import (matches server._gemini_smoke)
        from google.genai import types

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
        try:
            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(timeout=_CALL_TIMEOUT_MS),
            )
        except Exception:  # noqa: BLE001 - older SDKs may not accept http_options
            client = genai.Client(vertexai=True, project=project, location=location)

        video_part = types.Part.from_uri(file_uri=video_ref, mime_type=_mime_for(video_ref))
        resp = client.models.generate_content(
            model=MODEL,
            contents=[video_part, types.Part.from_text(text=_PROMPT)],
        )
        data = _parse_json(resp.text or "")
        steps = data.get("reproduction_steps") or []
        timeline = data.get("timeline") or []
        result = {
            "ok": True,
            "enabled": True,
            "video_ref": video_ref,
            "surfaced_symptom": str(data.get("surfaced_symptom") or "")[:500],
            "reproduction_steps": [str(s)[:300] for s in steps][:20],
            "timeline": [
                {"t": str(e.get("t") or "")[:12], "event": str(e.get("event") or "")[:300]}
                for e in timeline
                if isinstance(e, dict)
            ][:30],
            "reminder": "video shows the symptom only; confirm the cause in logs/config "
            "before concluding, and never open a PR from the video alone",
        }
        _log("INFO", "video_analyzed", video_ref=video_ref,
             steps=len(result["reproduction_steps"]), timeline=len(result["timeline"]))
        return result
    except Exception as e:  # noqa: BLE001 - video analysis must never break an incident run
        _log("WARNING", "video_analyze_failed", error=f"{type(e).__name__}: {e}")
        return {"ok": False, "enabled": True, "video_ref": video_ref, "error": f"{type(e).__name__}: {e}"}
