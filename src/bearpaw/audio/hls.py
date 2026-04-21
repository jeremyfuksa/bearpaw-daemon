"""HLS file-serving helper.

Thin wrapper over the capture output directory: resolves playlist and
segment paths, validates segment filenames to prevent path traversal,
and reports whether the stream is currently ready to serve. The actual
HLS muxing happens inside ffmpeg (see `AudioCapture`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from bearpaw.audio.capture import AudioCapture, SEGMENT_PREFIX


# Only files matching this pattern may be served from the output dir.
# ffmpeg writes segments named e.g. "seg_00001.ts"; the leading
# SEGMENT_PREFIX_ ensures clients can't request arbitrary files.
_SEGMENT_FILENAME = re.compile(rf"^{re.escape(SEGMENT_PREFIX)}_\d+\.ts$")


class HLSStream:
    """Resolve and validate HLS artifact paths from the capture output dir."""

    def __init__(self, capture: AudioCapture) -> None:
        self._capture = capture

    @property
    def output_dir(self) -> Path:
        return self._capture.output_dir

    @property
    def playlist_path(self) -> Path:
        return self._capture.playlist_path

    def is_ready(self) -> bool:
        """Return True once ffmpeg has written the playlist at least once."""
        return self._capture.playlist_ready()

    def resolve_segment(self, name: str) -> Optional[Path]:
        """Return the absolute path for a segment, or None if invalid / missing.

        Rejects names that could traverse outside the output dir or that
        don't match the expected ffmpeg-generated segment pattern.
        """
        if not _SEGMENT_FILENAME.match(name):
            return None
        path = (self.output_dir / name).resolve()
        try:
            path.relative_to(self.output_dir.resolve())
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path
