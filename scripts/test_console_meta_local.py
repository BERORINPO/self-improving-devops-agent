"""Offline smoke for /console-meta + /report-video (no cloud access).

Covers the default-off contract (unset env -> zero behavior change), the console
key gate, the video-availability predicate, the TTL cache + invalidation, and
the single-range (206) slicing — GCS is faked via sys.modules so nothing here
touches the network.

Run: PYTHONPATH=packages/agent/src python scripts/test_console_meta_local.py
"""
import os
import sys
import types

for k in ("AUTOSRE_CASES_TABLE", "AUTOSRE_VIDEO_ENABLED", "AUTOSRE_REPORT_VIDEO_URI",
          "AUTOSRE_VIDEO_BUCKET", "AUTOSRE_CONSOLE_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

import agents.server as server  # noqa: E402

client = TestClient(server.app)

_FAKE_BYTES = b"0123456789" * 4  # 40 bytes


def _install_fake_gcs() -> None:
    """Fake google.cloud.storage: Client().bucket().get_blob() -> tiny blob."""

    class _Blob:
        size = len(_FAKE_BYTES)

        def download_as_bytes(self, timeout=None):
            return _FAKE_BYTES

    class _Bucket:
        def get_blob(self, name, timeout=None):
            return _Blob()

    class _Client:
        def __init__(self, project=None):
            pass

        def bucket(self, name):
            return _Bucket()

    fake = types.ModuleType("google.cloud.storage")
    fake.Client = _Client
    sys.modules["google.cloud.storage"] = fake
    import google.cloud

    google.cloud.storage = fake


PASSED = 0
FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS {name}")
    else:
        FAILED += 1
        print(f"FAIL {name} {detail}")


# --- default-off: unset env must mean inert endpoints, no BQ/GCS calls ---
server._invalidate_console_meta()
r = client.get("/console-meta")
check("console_meta_default_off", r.status_code == 200
      and r.json() == {"memory": {"enabled": False},
                       "video": {"enabled": False, "available": False}}, str(r.json()))
r = client.get("/report-video")
check("report_video_default_off_404", r.status_code == 404, str(r.status_code))

# --- console key gate (report-video only; console-meta stays open) ---
os.environ["AUTOSRE_CONSOLE_KEY"] = "testkey"
check("report_video_gated_401", client.get("/report-video").status_code == 401)
check("report_video_key_but_unconfigured_404",
      client.get("/report-video?key=testkey").status_code == 404)
check("console_meta_stays_open", client.get("/console-meta").status_code == 200)

# --- availability predicate matches /report-video's own gate (gs:// only) ---
os.environ["AUTOSRE_VIDEO_ENABLED"] = "1"
os.environ["AUTOSRE_REPORT_VIDEO_URI"] = "https://example.com/not-gcs.mp4"
server._invalidate_console_meta()
r = client.get("/console-meta")
check("available_false_for_non_gs_uri",
      r.json()["video"] == {"enabled": True, "available": False}, str(r.json()))
check("report_video_non_gs_404", client.get("/report-video?key=testkey").status_code == 404)

# --- TTL cache: cached within TTL, recomputed after invalidation ---
os.environ["AUTOSRE_REPORT_VIDEO_URI"] = "gs://fake-bucket/clip.mp4"
r1 = client.get("/console-meta")  # still serves the cached non-gs snapshot
check("console_meta_served_from_cache",
      r1.json()["video"]["available"] is False, str(r1.json()))
server._invalidate_console_meta()
r2 = client.get("/console-meta")
check("console_meta_recomputed_after_invalidate",
      r2.json()["video"] == {"enabled": True, "available": True}, str(r2.json()))

# --- range slicing against a faked GCS blob ---
_install_fake_gcs()
r = client.get("/report-video?key=testkey")
check("report_video_200_full", r.status_code == 200 and r.content == _FAKE_BYTES
      and r.headers.get("accept-ranges") == "bytes"
      and r.headers.get("x-content-type-options") == "nosniff",
      f"{r.status_code} {dict(r.headers)}")
r = client.get("/report-video?key=testkey", headers={"Range": "bytes=2-5"})
check("report_video_206_slice", r.status_code == 206 and r.content == _FAKE_BYTES[2:6]
      and r.headers.get("content-range") == f"bytes 2-5/{len(_FAKE_BYTES)}",
      f"{r.status_code} {r.content!r} {r.headers.get('content-range')}")
r = client.get("/report-video?key=testkey", headers={"Range": "bytes=5-"})
check("report_video_206_open_end", r.status_code == 206 and r.content == _FAKE_BYTES[5:],
      f"{r.status_code}")
r = client.get("/report-video?key=testkey", headers={"Range": f"bytes={len(_FAKE_BYTES) + 10}-"})
check("report_video_range_past_end_falls_back_200", r.status_code == 200,
      str(r.status_code))

print(f"{PASSED}/{PASSED + FAILED} pass")
sys.exit(0 if FAILED == 0 else 1)
