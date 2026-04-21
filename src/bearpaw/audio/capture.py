"""ffmpeg-based HLS capture subprocess manager.

Spawns a long-lived ffmpeg subprocess that reads audio from a system
input (ALSA on Linux/Pi, AVFoundation on macOS, dshow on Windows) and
writes a live HLS stream (m3u8 playlist + MPEG-TS segments) to a
directory. Bearpaw's FastAPI layer serves those files verbatim — we
rely on ffmpeg's proven HLS muxer rather than hand-rolling MPEG-TS.

The subprocess is supervised: if ffmpeg exits unexpectedly it is
restarted with an exponential backoff, matching the reconnect pattern
used by `SerialTransport`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from bearpaw.config import AudioConfig


logger = logging.getLogger("bearpaw.audio")


# Must match ffmpeg's default HLS playlist name for consistency.
PLAYLIST_NAME = "live.m3u8"
SEGMENT_PREFIX = "seg"


class AudioCapture:
    """Manages a long-lived ffmpeg HLS capture subprocess.

    Use as an async context manager or via explicit start()/stop(). The
    capture loop supervises the subprocess: if ffmpeg exits, we log the
    failure and restart with exponential backoff until stop() is called.
    """

    # Backoff schedule (seconds) between restart attempts. The last entry
    # repeats indefinitely until stop() is called or the process stays up.
    RESTART_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._supervisor_task: Optional[asyncio.Task[None]] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stopping = asyncio.Event()
        self._ffmpeg_path: Optional[str] = None

    @property
    def output_dir(self) -> Path:
        return Path(self.config.output_dir)

    @property
    def playlist_path(self) -> Path:
        return self.output_dir / PLAYLIST_NAME

    def resolve_ffmpeg(self) -> str:
        """Locate the ffmpeg binary, honoring config override."""
        if self._ffmpeg_path:
            return self._ffmpeg_path
        candidate = self.config.ffmpeg_path or shutil.which("ffmpeg")
        if not candidate:
            raise RuntimeError(
                "ffmpeg not found on PATH; install it or set audio.ffmpeg_path"
            )
        self._ffmpeg_path = candidate
        return candidate

    def build_command(self) -> List[str]:
        """Compose the ffmpeg command line for HLS output."""
        cfg = self.config
        ffmpeg = self.resolve_ffmpeg()
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-f",
            cfg.input_format,
            "-i",
            cfg.device,
            "-ac",
            "1",
            "-ar",
            str(cfg.sample_rate),
            "-c:a",
            "aac",
            "-b:a",
            f"{cfg.bitrate}k",
            "-f",
            "hls",
            "-hls_time",
            str(cfg.segment_duration),
            "-hls_list_size",
            str(cfg.buffer_segments),
            "-hls_flags",
            "delete_segments+program_date_time+omit_endlist+independent_segments",
            "-hls_segment_filename",
            str(self.output_dir / f"{SEGMENT_PREFIX}_%05d.ts"),
            str(self.playlist_path),
        ]

    def _prepare_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Clear stale segments/playlist from a prior run so clients don't
        # see mixed content before ffmpeg rewrites the playlist.
        for entry in self.output_dir.iterdir():
            if entry.is_file() and (
                entry.name == PLAYLIST_NAME or entry.name.startswith(SEGMENT_PREFIX)
            ):
                try:
                    entry.unlink()
                except OSError as exc:
                    logger.warning(
                        "Failed to remove stale HLS artifact %s: %s", entry, exc
                    )

    async def start(self) -> None:
        """Start the supervisor loop. Returns immediately; capture runs async."""
        if self._supervisor_task and not self._supervisor_task.done():
            return
        self._stopping.clear()
        self._prepare_output_dir()
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(), name="audio-capture-supervisor"
        )
        logger.info(
            "AudioCapture started (device=%s format=%s output=%s)",
            self.config.device,
            self.config.input_format,
            self.output_dir,
        )

    async def stop(self) -> None:
        """Signal the supervisor to stop and wait for it to exit."""
        self._stopping.set()
        await self._terminate_process()
        if self._supervisor_task:
            try:
                await asyncio.wait_for(self._supervisor_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("AudioCapture supervisor did not exit within 5s")
                self._supervisor_task.cancel()
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        logger.info("AudioCapture stopped")

    async def _terminate_process(self) -> None:
        proc = self._process
        if not proc:
            return
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("ffmpeg did not terminate; killing")
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

    async def _supervisor_loop(self) -> None:
        attempt = 0
        while not self._stopping.is_set():
            start_ts = asyncio.get_event_loop().time()
            try:
                await self._run_once()
            except FileNotFoundError as exc:
                # ffmpeg binary missing — no point retrying blindly.
                logger.error("ffmpeg not found: %s", exc)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Audio capture iteration failed")

            if self._stopping.is_set():
                break

            # If the process stayed up for a while, reset the backoff.
            elapsed = asyncio.get_event_loop().time() - start_ts
            if elapsed > 60:
                attempt = 0
            delay = self.RESTART_BACKOFF_SECONDS[
                min(attempt, len(self.RESTART_BACKOFF_SECONDS) - 1)
            ]
            attempt += 1
            logger.warning(
                "ffmpeg exited (uptime=%.1fs); restarting in %.1fs", elapsed, delay
            )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                break  # stop requested during backoff
            except asyncio.TimeoutError:
                continue

    async def _run_once(self) -> None:
        cmd = self.build_command()
        logger.debug("Spawning ffmpeg: %s", " ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr so the pipe doesn't fill and block ffmpeg.
        stderr_task = asyncio.create_task(self._drain_stderr(self._process))
        try:
            rc = await self._process.wait()
        finally:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
        if rc != 0 and not self._stopping.is_set():
            logger.warning("ffmpeg exited with code %d", rc)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("ffmpeg: %s", text)

    def is_running(self) -> bool:
        proc = self._process
        return bool(
            self._supervisor_task
            and not self._supervisor_task.done()
            and proc is not None
            and proc.returncode is None
        )

    def playlist_ready(self) -> bool:
        """Has ffmpeg written a playlist yet?"""
        try:
            return (
                self.playlist_path.is_file() and os.path.getsize(self.playlist_path) > 0
            )
        except OSError:
            return False
