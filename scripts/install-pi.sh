#!/usr/bin/env bash
#
# Install Bearpaw as a systemd service on a Raspberry Pi (or any Debian-
# based Linux host).
#
# What this does, in order:
#   1. Verifies the host looks like a Debian-family Linux with Python 3.10+
#   2. Installs system packages: ffmpeg, libusb-1.0-0-dev
#   3. Creates a `scanner` system user/group with dialout + audio membership
#      (needed for /dev/ttyACM0 and ALSA capture respectively)
#   4. Installs the daemon into /opt/bearpaw/venv (isolated from system Python)
#   5. Creates /usr/local/bin/bearpaw wrapper pointing at the venv
#   6. Seeds /etc/bearpaw/config.yaml from config.example.yaml (only if the
#      target doesn't already exist — we never clobber your config)
#   7. Installs the systemd unit and reloads systemd (does not start it)
#   8. Adds a tmpfs entry for /tmp/bearpaw-hls to /etc/fstab and mounts it,
#      so HLS segment rotation doesn't wear the SD card
#
# The script is idempotent: re-run it after edits, upgrades, or a failed
# run without side effects. It does NOT automatically start the service —
# edit /etc/bearpaw/config.yaml first, then `sudo systemctl start bearpaw`.
#
# Usage:
#   sudo ./scripts/install-pi.sh           # install or update
#   sudo ./scripts/install-pi.sh --help    # show this help

set -euo pipefail

INSTALL_DIR="/opt/bearpaw"
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_DIR="/etc/bearpaw"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
SYSTEMD_UNIT="/etc/systemd/system/bearpaw.service"
BIN_WRAPPER="/usr/local/bin/bearpaw"
TMPFS_MOUNT="/tmp/bearpaw-hls"
TMPFS_FSTAB_MARKER="# bearpaw: HLS segment tmpfs"

SCANNER_USER="scanner"
SCANNER_GROUP="scanner"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

log() {
    printf '\033[1;34m[bearpaw-install]\033[0m %s\n' "$*"
}

warn() {
    printf '\033[1;33m[bearpaw-install]\033[0m %s\n' "$*" >&2
}

die() {
    printf '\033[1;31m[bearpaw-install]\033[0m %s\n' "$*" >&2
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "Must be run as root. Try: sudo $0"
    fi
}

preflight() {
    log "Preflight checks"
    if [[ "$(uname -s)" != "Linux" ]]; then
        die "This installer targets Linux. Detected: $(uname -s)"
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        die "apt-get not found; this installer assumes a Debian-family distro (Raspberry Pi OS, Ubuntu, Debian)."
    fi
    local python_bin
    python_bin="$(command -v python3 || true)"
    if [[ -z "${python_bin}" ]]; then
        die "python3 not found on PATH."
    fi
    local pyver
    pyver="$("${python_bin}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if ! "${python_bin}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        die "Python 3.10+ required; found ${pyver}."
    fi
    log "Found python3 ${pyver} at ${python_bin}"
}

install_apt_packages() {
    log "Installing system packages (ffmpeg, libusb-1.0-0-dev, python3-venv)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libusb-1.0-0-dev \
        python3-venv
}

ensure_user() {
    if ! getent group "${SCANNER_GROUP}" >/dev/null; then
        log "Creating group ${SCANNER_GROUP}"
        groupadd --system "${SCANNER_GROUP}"
    fi
    if ! id "${SCANNER_USER}" >/dev/null 2>&1; then
        log "Creating system user ${SCANNER_USER}"
        useradd \
            --system \
            --gid "${SCANNER_GROUP}" \
            --home-dir "${INSTALL_DIR}" \
            --shell /usr/sbin/nologin \
            "${SCANNER_USER}"
    fi
    for extra_group in dialout audio; do
        if getent group "${extra_group}" >/dev/null; then
            if ! id -nG "${SCANNER_USER}" | tr ' ' '\n' | grep -qx "${extra_group}"; then
                log "Adding ${SCANNER_USER} to ${extra_group} group"
                usermod -aG "${extra_group}" "${SCANNER_USER}"
            fi
        else
            warn "Group '${extra_group}' doesn't exist on this system; skipping."
        fi
    done
}

install_app() {
    log "Installing bearpaw into ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    # Sync the repo into /opt/bearpaw. Using cp -a preserves perms and is
    # safe to re-run. --no-target-directory avoids nesting on reinstall.
    rsync -a --delete \
        --exclude ".git" \
        --exclude "__pycache__" \
        --exclude "*.egg-info" \
        --exclude "venv" \
        "${REPO_ROOT}/" "${INSTALL_DIR}/"

    if [[ ! -d "${VENV_DIR}" ]]; then
        log "Creating venv at ${VENV_DIR}"
        python3 -m venv "${VENV_DIR}"
    fi
    log "Installing Python dependencies"
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
    "${VENV_DIR}/bin/pip" install --quiet -e "${INSTALL_DIR}"

    chown -R "${SCANNER_USER}:${SCANNER_GROUP}" "${INSTALL_DIR}"
}

install_wrapper() {
    log "Installing wrapper at ${BIN_WRAPPER}"
    cat >"${BIN_WRAPPER}" <<EOF
#!/usr/bin/env bash
# Auto-generated by bearpaw install-pi.sh
exec "${VENV_DIR}/bin/bearpaw" "\$@"
EOF
    chmod 0755 "${BIN_WRAPPER}"
}

seed_config() {
    mkdir -p "${CONFIG_DIR}"
    if [[ -e "${CONFIG_FILE}" ]]; then
        log "${CONFIG_FILE} already exists; leaving it alone"
    else
        log "Seeding ${CONFIG_FILE} from config.example.yaml"
        install -m 0644 "${INSTALL_DIR}/config.example.yaml" "${CONFIG_FILE}"
        chown root:"${SCANNER_GROUP}" "${CONFIG_FILE}"
    fi
}

install_systemd_unit() {
    log "Installing systemd unit at ${SYSTEMD_UNIT}"
    install -m 0644 \
        "${INSTALL_DIR}/packaging/systemd/bearpaw.service" \
        "${SYSTEMD_UNIT}"
    systemctl daemon-reload
    if ! systemctl is-enabled bearpaw >/dev/null 2>&1; then
        log "Enabling bearpaw.service (will start on boot)"
        systemctl enable bearpaw
    fi
}

setup_tmpfs() {
    # Keep HLS segment churn off the SD card.
    if grep -q "${TMPFS_FSTAB_MARKER}" /etc/fstab 2>/dev/null; then
        log "tmpfs entry already in /etc/fstab"
    else
        log "Adding tmpfs mount for ${TMPFS_MOUNT} to /etc/fstab"
        cat >>/etc/fstab <<EOF

${TMPFS_FSTAB_MARKER}
tmpfs ${TMPFS_MOUNT} tmpfs nodev,nosuid,size=32M,uid=${SCANNER_USER},gid=${SCANNER_GROUP},mode=0755 0 0
EOF
    fi
    mkdir -p "${TMPFS_MOUNT}"
    if ! mountpoint -q "${TMPFS_MOUNT}"; then
        log "Mounting ${TMPFS_MOUNT}"
        mount "${TMPFS_MOUNT}"
    fi
}

summary() {
    cat <<EOF

$(printf '\033[1;32m')Bearpaw installed.$(printf '\033[0m')

Next steps:
  1. Edit your config:       sudo \${EDITOR:-nano} ${CONFIG_FILE}
     (in particular, set audio.enabled: true and the correct ALSA device if
      you want HLS audio streaming; find it with: arecord -l)
  2. Start the service:      sudo systemctl start bearpaw
  3. Watch the logs:         sudo journalctl -u bearpaw -f
  4. Confirm the API:        curl http://localhost:8000/api/v1/status
  5. (If audio is on)        open http://<pi-ip>:8000/api/v1/stream/live.m3u8 in VLC

The service is enabled, so it will start automatically on boot once started.

EOF
}

main() {
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
    fi
    require_root
    preflight
    install_apt_packages
    ensure_user
    install_app
    install_wrapper
    seed_config
    install_systemd_unit
    setup_tmpfs
    summary
}

main "$@"
