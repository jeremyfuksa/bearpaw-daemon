# Changelog

All notable changes to `bearpaw-daemon` will be documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The HTTP + WebSocket API exposed by the daemon is a public contract.
Breaking changes to the API drive a major version bump; additive
changes drive a minor bump.

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
