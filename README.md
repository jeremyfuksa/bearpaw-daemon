# Bearpaw Daemon

Headless Python FastAPI service for Uniden scanner control and telemetry.

## Quickstart

1) Create and activate a venv in this repository root.
2) Install dependencies: `pip install -r requirements.txt` (or `pip install -e .`).
3) Copy `config.example.yaml` to your own config.
4) Run: `bearpaw-daemon --config ./config.yaml`.

## Config

See `docs/BACKEND_SPEC.md` for the schema and examples.

## Raspberry Pi audio streaming

Bearpaw can stream the scanner's audio as a live HLS feed alongside its
REST/WebSocket telemetry. The typical setup on a Pi:

1. Connect the scanner to the Pi via USB as usual (for control + telemetry).
2. Patch the scanner's headphone jack into a USB audio adapter connected
   to the Pi (the Pi's built-in audio is output-only).
3. Install ffmpeg: `sudo apt install ffmpeg`.
4. Find the ALSA device with `arecord -l` — typically `hw:1,0` for a
   single USB adapter.
5. In `config.yaml`, enable the audio section:
   ```yaml
   audio:
     enabled: true
     input_format: alsa
     device: "hw:1,0"
     output_dir: /tmp/bearpaw-hls
   ```
6. (Recommended) Mount `output_dir` as tmpfs so the rolling segments
   don't hit the SD card. Add to `/etc/fstab`:
   ```
   tmpfs /tmp/bearpaw-hls tmpfs nodev,nosuid,size=32M 0 0
   ```
7. Start the daemon. The HLS stream is available at:
   - Playlist: `http://<pi-ip>:8000/api/v1/stream/live.m3u8`
   - Works in VLC, Safari, iOS AVPlayer, and any HLS-capable player.

Live telemetry continues to be available via `/api/v1/*` REST endpoints
and the `/ws` WebSocket. Clients can pair HLS playback time (via the
playlist's `EXT-X-PROGRAM-DATE-TIME` tags) with WebSocket events to
build a synced "Now Playing" UI.

### Development on macOS

ffmpeg's `avfoundation` input works for local dev without a scanner:

```yaml
audio:
  enabled: true
  input_format: avfoundation
  device: ":1"  # index of your audio input; run `ffmpeg -f avfoundation -list_devices true -i ""` to list
```

## API

OpenAPI docs are served at `/docs` when the daemon is running. All
endpoints are grouped under tagged sections (status, commands, memory,
settings, analytics, preferences, stream) for discoverability by
external clients.
