# Bearpaw HLS Audio Streaming — Design Spec

**Date:** 2026-04-15
**Status:** Draft
**Scope:** Pi-side only — audio capture, HLS streaming, metadata sync

## Context

Bearpaw Daemon currently controls Uniden scanners (BC125AT, SR30C) and streams telemetry (frequency, modulation, RSSI, squelch state, channel tags) via REST API and WebSocket. It runs as a headless service with systemd support.

The goal is to extend Bearpaw so that when deployed on a Raspberry Pi physically connected to a scanner, it also captures the scanner's audio output (headphone jack → USB audio adapter → Pi) and serves it as an HLS stream alongside synchronized metadata. This turns the Pi into a self-contained scanner streaming appliance — listen from anywhere on the network with any HLS-compatible client (VLC, Safari, iOS AVPlayer).

This is the first phase of a larger vision: a native iOS app that provides always-on background scanner audio with a synced "Now Playing" overlay. This spec covers only the Pi/server side. The iOS app is a separate future project that will consume this stream.

## Design Decisions

- **HLS over Icecast/direct HTTP:** HLS is native to iOS AVPlayer, supports timed metadata (ID3 tags) for synced "Now Playing" data, is stateless HTTP (scales to multiple listeners without connection tracking), and keeps everything in a single Bearpaw process.
- **ffmpeg as subprocess over Python audio libraries:** ffmpeg is pre-built for ARM on Raspbian, handles ALSA capture and AAC encoding in C (not Python), and the subprocess boundary provides fault isolation — if ffmpeg crashes, Bearpaw restarts it.
- **In-memory segment buffer over disk:** Rolling buffer of ~180 KB in RAM avoids SD card wear and keeps latency predictable.
- **Audio is opt-in:** `audio.enabled: false` by default. Existing deployments are unaffected.

## Architecture

### Audio Capture Pipeline

**Hardware path:** Scanner headphone jack → 3.5mm cable → USB audio adapter (e.g., Plugable USB-AUDIO) → Pi ALSA device.

**`AudioCapture` class** (`src/bearpaw/audio/capture.py`):
- Spawns `ffmpeg` as an asyncio subprocess reading from the configured ALSA device
- ffmpeg encodes to AAC-LC mono at a configurable bitrate (default 64 kbps) and writes raw AAC frames to stdout
- Bearpaw reads frames from the subprocess pipe asynchronously
- On ffmpeg crash/exit: logs the error and restarts the subprocess with exponential backoff (matches existing transport reconnection pattern)
- Squelch-aware behavior: ffmpeg continuously encodes regardless of squelch state. Silence is encoded as silence. The metadata overlay distinguishes "scanning" from "active signal" — the audio stream itself is never interrupted.

**ffmpeg command (approximate):**
```
ffmpeg -f alsa -i hw:1,0 -ac 1 -ar 22050 -c:a aac -b:a 64k -f adts pipe:1
```

### HLS Segment Generation & Serving

**`HLSStream` class** (`src/bearpaw/audio/hls.py`):
- Receives AAC frames from `AudioCapture`
- Packages frames into 2-second MPEG-TS (.ts) segments
- TS muxing done with Python stdlib (`struct`, `io`) — the format is simple for single-stream mono AAC
- Maintains a rolling window of segments in memory (default 15 segments = 30 seconds)
- Generates and updates the `.m3u8` playlist pointing to current segments
- Injects ID3 timed metadata tags into each segment at seal time

**New FastAPI endpoints:**
- `GET /api/v1/stream/live.m3u8` — HLS playlist (`Content-Type: application/vnd.apple.mpegurl`, `Cache-Control: no-cache`)
- `GET /api/v1/stream/segment/{id}.ts` — Audio segments (`Content-Type: video/mp2t`, short cache TTL matching segment duration)

**Memory footprint:** 15 segments × ~12 KB each ≈ 180 KB. Negligible on any Pi model.

**Listener model:** Pure stateless HTTP. Each client polls the playlist independently and fetches segments. No connection tracking, no listener limits beyond network bandwidth.

### Metadata Synchronization

**Two-tier delivery:**

**Tier 1 — Embedded in HLS (timed, synced with audio):**
Each .ts segment carries an ID3 tag with a JSON snapshot of scanner state at the moment the segment was sealed. When the audio plays on the client, the metadata from that exact moment arrives with it.

Payload per segment:
```json
{
  "freq": 462.5625,
  "mod": "FM",
  "chan": 12,
  "tag": "FRS Ch1",
  "rssi": -45,
  "squelch": "open",
  "ts": 1713200000.123
}
```

**Tier 2 — Existing WebSocket (real-time, not synced with audio):**
The current `/ws` endpoint continues unchanged, delivering live state with sub-second latency. Useful for remote control and "what's happening right now" (vs "what am I hearing"). A future iOS app can use both: HLS metadata for the player UI, WebSocket for live control.

**Metadata source:** Both tiers read from the existing `StateStore`. `HLSStream` snapshots `LiveState` when sealing each segment. No new polling or state management needed.

### Integration with Existing Architecture

**New modules:**
- `src/bearpaw/audio/__init__.py`
- `src/bearpaw/audio/capture.py` — `AudioCapture` class
- `src/bearpaw/audio/hls.py` — `HLSStream` class

**Config additions** (`config.yaml`):
```yaml
audio:
  enabled: false
  device: "hw:1,0"
  bitrate: 64
  segment_duration: 2
  buffer_segments: 15
```

**Startup flow:** After scanner transport and state store initialize, if `audio.enabled` is true:
1. Start `AudioCapture` (spawns ffmpeg)
2. Start `HLSStream` (begins reading frames, generating segments)
3. Register `/api/v1/stream/` routes

If audio is disabled, nothing changes. All existing functionality (scanner control, telemetry, analytics, exporters) is unaffected.

**Dependencies:**
- `ffmpeg` — system package (`apt install ffmpeg` on Raspbian). Not a Python dependency.
- No new Python packages. Segment muxing and ID3 injection use stdlib (`struct`, `io`, `asyncio`).

**Lifecycle:** `AudioCapture` registers with the existing shutdown handler. On daemon stop: ffmpeg subprocess is terminated, HLS buffer is cleared, stream endpoints return 503.

## Verification Plan

1. **Audio capture:** Run Bearpaw with `audio.enabled: true` on the Pi with USB sound card. Confirm ffmpeg starts and frames are read (check logs).

2. **HLS playback in VLC:** Open `http://<pi-ip>:8000/api/v1/stream/live.m3u8` in VLC. Confirm scanner audio plays with ~6-10 sec delay.

3. **Metadata in Safari:** Open the same URL in Safari. Use developer tools to inspect ID3 metadata arriving with each segment.

4. **Existing functionality:** Run existing tests and replay tooling to confirm scanner control, WebSocket, analytics, and exporters work with audio both enabled and disabled.

5. **Stability:** Run for several hours. Confirm memory stays flat, ffmpeg stays healthy, segment counter rolls over cleanly.

6. **Unit tests:** TS packet construction, ID3 tag injection, and playlist generation tested with synthetic AAC frames (no hardware dependency).

## Future Work (Out of Scope)

- **Native iOS app** with AVPlayer, background audio, lock-screen controls, and synced "Now Playing" UI
- **CarPlay support** (hard requirement) — the iOS app must work as a CarPlay audio app with playback controls and "Now Playing" metadata on the car's display
- **Remote scanner control from iOS** — Bearpaw's REST API already supports hold, scan, key commands, lockouts, bank toggling, and full settings. The iOS app can be a complete scanner remote, not just a listener. No new Pi-side work needed for this — the API exists today.
- Remote access via Tailscale/WireGuard
- Push notifications for priority channel activity
- Audio recording/archival
