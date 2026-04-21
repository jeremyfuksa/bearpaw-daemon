"""Live HLS audio streaming subsystem.

Captures scanner audio from the host's audio input (typically a USB audio
adapter on a Raspberry Pi with the scanner's headphone jack patched in),
encodes to AAC, and exposes a standard HLS stream (playlist + segments)
that any HLS-compatible client can consume.

Metadata is delivered separately via the existing WebSocket, using HLS
`EXT-X-PROGRAM-DATE-TIME` so clients can align audio playback time with
telemetry events they receive over the wire.
"""

from bearpaw.audio.capture import AudioCapture
from bearpaw.audio.hls import HLSStream

__all__ = ["AudioCapture", "HLSStream"]
