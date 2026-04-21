# Bearpaw Daemon

Headless Python FastAPI service for Uniden scanner control and telemetry.

## Quickstart

1) Create and activate a venv in this repository root.
2) Install dependencies: `pip install -r requirements.txt` (or `pip install -e .`).
3) Copy `config.example.yaml` to your own config.
4) Run: `bearpaw-daemon --config ./config.yaml`.

## Config

See `docs/BACKEND_SPEC.md` for the schema and examples.

## Raspberry Pi installation

For a production Pi deployment, use the installer:

```bash
git clone https://github.com/jeremyfuksa/bearpaw-daemon.git
cd bearpaw-daemon
sudo ./scripts/install-pi.sh
```

The installer is idempotent — safe to re-run after updates. It:

1. Installs system packages (`ffmpeg`, `libusb-1.0-0-dev`, `python3-venv`)
2. Creates a `scanner` system user with `dialout` and `audio` group
   membership (for `/dev/ttyACM0` and ALSA access respectively)
3. Installs the daemon into `/opt/bearpaw/venv`
4. Creates `/usr/local/bin/bearpaw` as a wrapper pointing at the venv
5. Seeds `/etc/bearpaw/config.yaml` from `config.example.yaml` (only if
   it doesn't already exist — your config is never clobbered)
6. Installs the systemd unit and enables it (does not start it)
7. Adds a tmpfs mount for `/tmp/bearpaw-hls` to `/etc/fstab` so HLS
   segment rotation doesn't wear the SD card

After install, edit `/etc/bearpaw/config.yaml` (at minimum pick the
right serial port and, if you want HLS audio, set `audio.enabled: true`
and the correct ALSA device from `arecord -l`), then:

```bash
sudo systemctl start bearpaw
sudo journalctl -u bearpaw -f   # watch logs
```

To upgrade: `git pull`, then `sudo ./scripts/install-pi.sh` again.

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
