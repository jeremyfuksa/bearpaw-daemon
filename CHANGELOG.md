# Changelog

All notable changes to `bearpaw-daemon` will be documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The HTTP + WebSocket API exposed by the daemon is a public contract.
Breaking changes to the API drive a major version bump; additive
changes drive a minor bump.

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

### Changed

- Repository layout flattened: `apps/daemon/*` is now the repository
  root. Install paths and import paths are unchanged.
- Distributed via PyPI as `bearpaw-daemon`. Both `pip install
  bearpaw-daemon` (generic) and `sudo ./scripts/install-pi.sh` (Pi
  systemd setup) are supported.
- README rewritten for first-time install by someone other than the
  author.

## [1.0.0] — internal

Pre-public baseline. Full Uniden BC125AT and SR30C control protocol,
USB and serial transports with reconnection, analytics database,
exporters (text file, JSON stream, MQTT), idempotent Pi installer,
systemd unit. Not released to PyPI.
