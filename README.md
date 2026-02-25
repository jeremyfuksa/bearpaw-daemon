# Bearpaw Daemon

Headless Python FastAPI service for Uniden scanner control and telemetry.

## Quickstart

1) Create and activate a venv in this repository root.
2) Install dependencies: `pip install -r requirements.txt` (or `pip install -e .`).
3) Copy `config.example.yaml` to your own config.
4) Run: `bearpaw-daemon --config ./config.yaml`.

## Config

See `docs/BACKEND_SPEC.md` for the schema and examples.
