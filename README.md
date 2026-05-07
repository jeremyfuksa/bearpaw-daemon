# bearpaw-daemon

Headless control and telemetry service for Uniden BC125AT and SR30C
handheld scanners. Exposes an HTTP + WebSocket API designed as a
first-class contract for any client that wants to drive a scanner —
dashboards, kiosks, voice assistants, custom integrations.

The daemon's HTTP API (documented via OpenAPI at `/openapi.json` and
`/docs`) is the public contract. Any consumer that speaks HTTP and
WebSocket can use it.

## Install

```bash
pip install bearpaw-daemon
# or
uv pip install bearpaw-daemon
```

Requires Python 3.10+. On Linux you'll need `libusb-1.0` available at
runtime; `apt install libusb-1.0-0` covers it on Debian-family systems.

## Running

```bash
cp config.example.yaml config.yaml   # tune as needed
bearpaw --config ./config.yaml
```

The daemon starts on `127.0.0.1:8000` by default. Browse `/docs` for
the live OpenAPI UI, or `/openapi.json` for the raw schema.

### Generating typed clients

The OpenAPI document is the canonical contract. Generate clients with
your tool of choice:

```bash
# Python
openapi-python-client generate --url http://localhost:8000/openapi.json

# TypeScript
npx openapi-typescript http://localhost:8000/openapi.json -o bearpaw.d.ts
```

## Raspberry Pi installation

For a production Pi deployment, use the installer:

```bash
git clone https://github.com/jeremyfuksa/bearpaw-daemon.git
cd bearpaw-daemon
sudo ./scripts/install-pi.sh
```

The installer is idempotent — safe to re-run after updates. It:

1. Installs system packages (`libusb-1.0-0-dev`, `python3-venv`)
2. Creates a `scanner` system user with `dialout` group membership
   (for `/dev/ttyACM0` access)
3. Installs the daemon into `/opt/bearpaw/venv`
4. Creates `/usr/local/bin/bearpaw` as a wrapper pointing at the venv
5. Seeds `/etc/bearpaw/config.yaml` from `config.example.yaml` (only if
   it doesn't already exist — your config is never clobbered)
6. Installs the systemd unit and enables it (does not start it)

After install, edit `/etc/bearpaw/config.yaml` (at minimum, pick the
right serial port for your scanner), then:

```bash
sudo systemctl start bearpaw
sudo journalctl -u bearpaw -f   # watch logs
```

To upgrade: `git pull`, then re-run the installer.

## Hardware notes

- **Scanner cable:** USB-A to mini-B (BC125AT) or USB-C (SR30C).
- **PC mode:** Some Uniden scanners need to be put into "PC/IF" mode
  manually before they accept serial commands. Consult your scanner's
  manual.
- **Permissions on Linux:** The daemon needs read/write access to the
  scanner's serial device (typically `/dev/ttyACM0`). Either add your
  user to the `dialout` group or run via the systemd unit, which uses
  the `scanner` system user.
- **USB transport:** USB transport is the default and preferred path
  on the BC125AT. Use `transport: serial` in `config.yaml` only if you
  have a specific reason.
- **ALSA discovery for audio consumers:** `arecord -l` lists capture
  devices; the typical USB audio adapter shows up as `hw:1,0`.

## Audio

The daemon does not stream audio. Scanner audio is hardware passthrough
from the scanner's headphone jack to whatever you want — speakers
directly, an ALSA loopback into another process, an Icecast encoder,
etc. Consumers that want software-gated audio can subscribe to the
`squelch_open` event on the WebSocket and gate their own pipeline.

## API

OpenAPI docs are served at `/docs` when the daemon is running.
Endpoints are grouped by tag (status, commands, memory, settings,
analytics, preferences) for discoverability.

## Config

See the full schema in `config.example.yaml`.

## Development

```bash
git clone https://github.com/jeremyfuksa/bearpaw-daemon.git
cd bearpaw-daemon
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest pytest-asyncio pytest-cov ruff
pytest
```

See `TESTING.md` for the test layout and hardware-in-the-loop guidance.

## License

MIT.
