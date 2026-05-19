# Changelog

All notable changes to `bearpaw-daemon` will be documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The HTTP + WebSocket API exposed by the daemon is a public contract.
Breaking changes to the API drive a major version bump; additive
changes drive a minor bump.

## [Unreleased]

### Added

- WebSocket `subscribe` messages now accept an optional `live` boolean.
  When omitted or `true`, the subscriber forces the daemon to poll at
  `polling.sts_interval` while subscribed to the `state` topic (the
  v1.3.0 behavior). When `false`, the subscriber is treated as passive
  and the daemon stays on `polling.idle_sts_interval` even while the
  client is connected. Lets always-on kiosk clients opt out of fast
  polling so the BC125AT's backlight can dim. (#16)

### Fixed

- v1.3.0's adaptive polling assumed any state subscriber wanted 10 Hz
  updates, which broke the wall-mounted kiosk case where the kiosk's
  WebSocket connection is always open even when no view needs
  high-frequency state. Kiosk clients can now send
  `{"type": "subscribe", "topics": [...], "live": false}` and the
  daemon will stay at the idle poll rate. (#16)

## [1.3.0] — 2026-05-18

### Changed

- Status polling (`STS`) is now adaptive. While at least one WebSocket
  client is subscribed to the `state` topic, polling runs at
  `polling.sts_interval` (default 10 Hz) as before. When no client is
  subscribed, polling falls back to the new
  `polling.idle_sts_interval` (default 1 Hz). This lets the BC125AT's
  backlight dim during unattended scanning instead of being held lit by
  back-to-back protocol commands, which matters for wall-mounted kiosk
  installs. The fast rate is restored immediately on the next poll once
  a client subscribes. (#16)

### Added

- `--poll-interval` and `--idle-poll-interval` CLI flags on `bearpaw`
  override `polling.sts_interval` and `polling.idle_sts_interval`
  without editing the config file. (#16)

## [1.2.0] — 2026-05-08

### Added

- `POST /api/v1/frequency` direct-tunes the radio to a given frequency
  (MHz), with optional `modulation`. On the BC125AT this emulates the
  front-panel keypad sequence (HOLD → digits → E), since the BC125AT
  has no single-shot direct-tune serial command. (#13)
- `POST /api/v1/commands/key` now accepts human-friendly key aliases
  (`UP`, `DOWN`, `MENU`, `FUNC`, `HOLD`, `ENTER`, `LOCKOUT`/`L_OUT`,
  ...) and translates them to the underlying Uniden serial KEY codes.
  Native single-character codes (`H`, `S`, `E`, `.`, `0`-`9`, etc.)
  still pass through unchanged. (#13)

## [1.1.1] — 2026-05-08

### Fixed

- Daemon crashed at startup on FastAPI >= 0.110 (current PyPI ships
  0.136 / Starlette 1.0) because `app.add_event_handler` was removed.
  Switched to the `lifespan` context manager. The `fastapi` dependency
  is now pinned to `>=0.110, <1.0`. (#10)

## [1.1.0] — 2026-05-07

First public release on PyPI as `bearpaw-daemon`.

### Removed

- HLS audio streaming has been removed. The `audio/` package, the
  `audio:` config section, the `/api/v1/stream/live.m3u8` and
  `/api/v1/stream/segment/{name}` routes, the `stream` OpenAPI tag,
  and the `ffmpeg` apt install plus `/tmp/bearpaw-hls` tmpfs setup in
  the Pi installer are gone. The daemon's job is hardware control;
  audio is downstream of the daemon. Consumers that want streaming
  audio can subscribe to the `squelch_open` event on the WebSocket
  and build their preferred pipeline (Icecast, Opus, raw PCM, etc.).

### Added

- `LICENSE` (MIT) ships in the source tree and in the wheel.
- `bearpaw --print-example-config` writes the bundled example config
  to stdout. The example file now ships inside the package as
  `bearpaw/config.example.yaml`, so `pip install bearpaw-daemon`
  users can produce a starting config without cloning the repo.

### Changed

- Repository layout flattened: `apps/daemon/*` is now the repository
  root. Install paths and import paths are unchanged.
- `config.example.yaml` moved to `src/bearpaw/config.example.yaml`
  (single source of truth, packaged as `package-data`). The Linux
  installer reads it from the new path.
- Distributed via PyPI as `bearpaw-daemon`. Both `pip install
  bearpaw-daemon` (generic) and `sudo ./scripts/install-linux.sh`
  (Debian-family systemd setup; Raspberry Pi OS is the typical case
  but nothing is Pi-specific) are supported.
- Renamed `scripts/install-pi.sh` to `scripts/install-linux.sh`. The
  installer was always Debian-family Linux generic — the new name
  reflects that.
- README rewritten for first-time install by someone other than the
  author.

## [1.0.0] — internal

Pre-public baseline. Full Uniden BC125AT and SR30C control protocol,
USB and serial transports with reconnection, analytics database,
exporters (text file, JSON stream, MQTT), idempotent Pi installer,
systemd unit. Not released to PyPI.
