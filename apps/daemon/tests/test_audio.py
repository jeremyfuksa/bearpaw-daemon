"""Tests for the audio subsystem (AudioCapture + HLSStream + routes).

Does not launch ffmpeg — we validate command construction, path
resolution, route behavior, and config defaults. Hardware and
subprocess integration is covered by manual verification on the Pi.
"""

import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from bearpaw.api import RuntimeState, create_app
from bearpaw.audio import AudioCapture, HLSStream
from bearpaw.audio.capture import PLAYLIST_NAME, SEGMENT_PREFIX
from bearpaw.config import AppConfig, AudioConfig, WebSocketConfig
from bearpaw.models import DeviceInfo, LiveState
from bearpaw.state import StateStore
from bearpaw.websocket import WebSocketManager


class _StubDriver:
    async def get_status(self):
        return LiveState(
            timestamp=time.time(),
            frequency=151.25,
            modulation="FM",
            squelch_open=True,
            rssi=75,
            mode="SCAN",
            channel=1,
            alpha_tag="TEST",
            volume=10,
            battery=100,
            stale=False,
        )

    async def send_hold(self):
        return True

    async def send_scan(self):
        return True

    async def send_key(self, key_code: str):
        return True

    async def read_channel(self, index: int):
        raise NotImplementedError

    async def detect_model(self):
        return "BC125AT"


class _StubScheduler:
    def has_high_priority(self):
        return False


class _StubTransport:
    def send_command(self, cmd: str):
        future = Future()
        future.set_result("OK")
        return future


def _build_runtime(app, tmp_dir: str, audio_enabled: bool) -> RuntimeState:
    state_store = StateStore(persistence=None)
    ws_config = WebSocketConfig()
    audio_config = AudioConfig(enabled=audio_enabled, output_dir=tmp_dir)
    app_config = AppConfig(audio=audio_config)

    audio_capture = AudioCapture(audio_config) if audio_enabled else None
    hls_stream = HLSStream(audio_capture) if audio_capture else None

    return RuntimeState(
        config=app_config,
        transport=_StubTransport(),
        scheduler=_StubScheduler(),
        driver=_StubDriver(),
        state_store=state_store,
        ws_manager=WebSocketManager(ws_config),
        device_info=DeviceInfo(
            model="BC125AT",
            port="/dev/ttyACM0",
            vid=0x1965,
            pid=0x0017,
            serial_number=None,
            description="Uniden Scanner",
        ),
        session_id="test-session",
        audio_capture=audio_capture,
        hls_stream=hls_stream,
    )


class AudioConfigDefaultsTests(unittest.TestCase):
    def test_defaults(self):
        cfg = AudioConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.input_format, "alsa")
        self.assertEqual(cfg.device, "hw:1,0")
        self.assertEqual(cfg.bitrate, 64)
        self.assertEqual(cfg.segment_duration, 2)
        self.assertEqual(cfg.buffer_segments, 15)
        self.assertEqual(cfg.output_dir, "/tmp/bearpaw-hls")

    def test_default_app_config_has_audio_disabled(self):
        self.assertFalse(AppConfig().audio.enabled)


class AudioCaptureCommandTests(unittest.TestCase):
    def test_command_includes_expected_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = AudioCapture(
                AudioConfig(output_dir=tmp, ffmpeg_path="/usr/bin/ffmpeg")
            )
            cmd = capture.build_command()

        self.assertEqual(cmd[0], "/usr/bin/ffmpeg")
        # Spot-check the high-signal flags rather than asserting exact order.
        self.assertIn("-f", cmd)
        self.assertIn("alsa", cmd)
        self.assertIn("hw:1,0", cmd)
        self.assertIn("-c:a", cmd)
        self.assertIn("aac", cmd)
        self.assertIn("hls", cmd)
        self.assertIn("-hls_time", cmd)
        self.assertTrue(
            any(f.endswith("live.m3u8") for f in cmd),
            f"Playlist not in command: {cmd}",
        )
        # The crucial HLS flags must all be present.
        flags_arg = cmd[cmd.index("-hls_flags") + 1]
        for required in (
            "delete_segments",
            "program_date_time",
            "omit_endlist",
        ):
            self.assertIn(required, flags_arg)

    def test_resolve_ffmpeg_respects_config(self):
        capture = AudioCapture(AudioConfig(ffmpeg_path="/custom/ffmpeg"))
        self.assertEqual(capture.resolve_ffmpeg(), "/custom/ffmpeg")

    def test_resolve_ffmpeg_errors_when_missing(self):
        capture = AudioCapture(AudioConfig(ffmpeg_path=None))
        with mock.patch("bearpaw.audio.capture.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                capture.resolve_ffmpeg()

    def test_prepare_output_dir_clears_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create stale playlist + segments plus an unrelated file.
            (Path(tmp) / PLAYLIST_NAME).write_bytes(b"old")
            (Path(tmp) / f"{SEGMENT_PREFIX}_00001.ts").write_bytes(b"old")
            (Path(tmp) / "unrelated.txt").write_bytes(b"keep me")

            capture = AudioCapture(AudioConfig(output_dir=tmp))
            capture._prepare_output_dir()

            self.assertFalse((Path(tmp) / PLAYLIST_NAME).exists())
            self.assertFalse((Path(tmp) / f"{SEGMENT_PREFIX}_00001.ts").exists())
            self.assertTrue((Path(tmp) / "unrelated.txt").exists())


class HLSStreamResolutionTests(unittest.TestCase):
    def test_resolve_segment_rejects_bad_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = AudioCapture(AudioConfig(output_dir=tmp))
            hls = HLSStream(capture)

            for bad in (
                "../etc/passwd",
                "seg_00001.ts/../../secret",
                "other.ts",
                "seg_abc.ts",
                "seg_.ts",
                "live.m3u8",
            ):
                self.assertIsNone(hls.resolve_segment(bad), f"accepted bad: {bad}")

    def test_resolve_segment_returns_path_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = AudioCapture(AudioConfig(output_dir=tmp))
            hls = HLSStream(capture)
            segment = Path(tmp) / f"{SEGMENT_PREFIX}_00042.ts"
            segment.write_bytes(b"fake ts data")

            resolved = hls.resolve_segment(f"{SEGMENT_PREFIX}_00042.ts")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved, segment.resolve())

    def test_resolve_segment_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = AudioCapture(AudioConfig(output_dir=tmp))
            hls = HLSStream(capture)
            self.assertIsNone(hls.resolve_segment(f"{SEGMENT_PREFIX}_99999.ts"))

    def test_is_ready_reflects_playlist_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = AudioCapture(AudioConfig(output_dir=tmp))
            hls = HLSStream(capture)
            self.assertFalse(hls.is_ready())
            capture.playlist_path.write_text("#EXTM3U\n")
            self.assertTrue(hls.is_ready())


class StreamRouteTests(unittest.TestCase):
    def _make_client(self, tmp: str, audio_enabled: bool) -> TestClient:
        app = create_app(
            AppConfig(audio=AudioConfig(enabled=audio_enabled, output_dir=tmp)),
            startup_enabled=False,
        )
        app.state.runtime = _build_runtime(app, tmp, audio_enabled=audio_enabled)
        return TestClient(app)

    def test_playlist_503_when_audio_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._make_client(tmp, audio_enabled=False)
            resp = client.get("/api/v1/stream/live.m3u8")
            self.assertEqual(resp.status_code, 503)

    def test_playlist_503_when_warming_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._make_client(tmp, audio_enabled=True)
            resp = client.get("/api/v1/stream/live.m3u8")
            self.assertEqual(resp.status_code, 503)
            # Error envelope is shaped by the global HTTPException handler.
            body = resp.json()
            self.assertEqual(body.get("error"), "audio_stream_warming_up")

    def test_playlist_served_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            playlist_body = b"#EXTM3U\n#EXT-X-VERSION:3\n"
            (Path(tmp) / PLAYLIST_NAME).write_bytes(playlist_body)
            client = self._make_client(tmp, audio_enabled=True)

            resp = client.get("/api/v1/stream/live.m3u8")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content, playlist_body)
            self.assertEqual(
                resp.headers["content-type"], "application/vnd.apple.mpegurl"
            )
            self.assertIn("no-cache", resp.headers["cache-control"])

    def test_segment_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / PLAYLIST_NAME).write_bytes(b"#EXTM3U\n")
            client = self._make_client(tmp, audio_enabled=True)

            resp = client.get("/api/v1/stream/segment/..%2Fetc%2Fpasswd")
            # FastAPI normalizes path; expect 404 either way (bad name or missing).
            self.assertEqual(resp.status_code, 404)

    def test_segment_served_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / PLAYLIST_NAME).write_bytes(b"#EXTM3U\n")
            segment = Path(tmp) / f"{SEGMENT_PREFIX}_00007.ts"
            segment.write_bytes(b"ts-bytes")

            client = self._make_client(tmp, audio_enabled=True)
            resp = client.get(f"/api/v1/stream/segment/{SEGMENT_PREFIX}_00007.ts")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content, b"ts-bytes")
            self.assertEqual(resp.headers["content-type"], "video/mp2t")

    def test_segment_404_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / PLAYLIST_NAME).write_bytes(b"#EXTM3U\n")
            client = self._make_client(tmp, audio_enabled=True)
            resp = client.get(f"/api/v1/stream/segment/{SEGMENT_PREFIX}_00999.ts")
            self.assertEqual(resp.status_code, 404)


class OpenAPIPolishTests(unittest.TestCase):
    def test_stream_endpoints_appear_in_openapi_with_stream_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                AppConfig(audio=AudioConfig(output_dir=tmp)), startup_enabled=False
            )
            client = TestClient(app)
            spec = client.get("/openapi.json").json()

        paths = spec["paths"]
        self.assertIn("/api/v1/stream/live.m3u8", paths)
        self.assertIn("/api/v1/stream/segment/{name}", paths)
        tags = {t["name"] for t in spec.get("tags", [])}
        self.assertIn("stream", tags)


if __name__ == "__main__":
    unittest.main()
