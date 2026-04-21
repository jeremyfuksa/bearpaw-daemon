# Packaging

Bearpaw is a Linux service intended to run on a Raspberry Pi connected
to a Uniden handheld scanner. Other platforms work for development but
are not supported deployment targets.

## systemd (production)

1. Install the daemon on the Pi (`pip install .` in a venv, or
   package with your preferred method).
2. Copy `systemd/bearpaw.service` to `/etc/systemd/system/`.
3. Put your config at `/etc/bearpaw/config.yaml`.
4. Create the `scanner` user and group referenced by the unit, or
   edit the unit to use your preferred account.
5. Enable and start:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable --now bearpaw
   ```

The unit uses `Type=simple` with `Restart=on-failure`, so systemd
handles supervision — the CLI `--daemon` flag is not needed in this
setup.
