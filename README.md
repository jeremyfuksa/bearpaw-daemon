# Bearpaw

Bearpaw is a self-contained scanner streaming appliance: a Raspberry
Pi wired to a Uniden handheld scanner acts as the control hub, with
clients (web dashboard and iOS app) consuming a first-class HTTP +
WebSocket + HLS API.

This repo is a monorepo housing every piece of the system.

## Layout

```
apps/
  daemon/       Python FastAPI service — scanner control, telemetry,
                analytics, HLS audio streaming. Runs on the Pi.
  web/          (future) web dashboard — scanner HUD + analytics,
                kiosk on the Pi's monitor AND a command-center view on
                other screens. Consumes the daemon's API.
  ios/          (future) native iOS app with CarPlay — background
                audio listener + full scanner remote. Consumes the
                daemon's API.

docs/           Cross-cutting specs and design documents.

.github/        CI — currently runs daemon tests + lint. Will grow
                per-app jobs as the web and iOS apps land.
```

## Getting started

- **Running the daemon on a Pi:** see [`apps/daemon/README.md`](apps/daemon/README.md)
- **Local daemon development:** `cd apps/daemon && pip install -e . && bearpaw-daemon --config ./config.example.yaml`

## Why a monorepo

All three apps share a tight API contract generated from the daemon's
OpenAPI schema. Monorepo means API changes and their client-side
updates land in one atomic commit, and `git log` covers the whole
system.

## Design docs

- [`docs/superpowers/specs/2026-04-15-hls-audio-streaming-design.md`](docs/superpowers/specs/2026-04-15-hls-audio-streaming-design.md) — HLS audio streaming design
