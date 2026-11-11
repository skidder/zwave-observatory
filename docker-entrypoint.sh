#!/bin/sh
# Entrypoint: optionally source DATA_DIR/secrets.env, then start uvicorn.
set -eu

DATA_DIR="${DATA_DIR:-/data}"
SECRETS_FILE="${DATA_DIR}/secrets.env"
APP_UID=10001

# Ensure the data dir exists and is writable by the app user. When the
# container starts as root (some NAS hosts default to this), chown the
# bind-mounted data dir so the non-root app process can write SQLite.
mkdir -p "${DATA_DIR}" 2>/dev/null || true
if [ "$(id -u)" = "0" ] && [ -d "${DATA_DIR}" ]; then
    chown -R "${APP_UID}:${APP_UID}" "${DATA_DIR}" || true
fi
if ! touch "${DATA_DIR}/.write-test" 2>/dev/null; then
    echo "ERROR: DATA_DIR (${DATA_DIR}) is not writable by uid $(id -u)." >&2
    echo "Fix on the host: mkdir -p <data dir> && chown -R 10001:10001 <data dir>" >&2
    echo "Or set 'user: \"0:0\"' on the service in docker-compose.yml so the" >&2
    echo "entrypoint can fix ownership itself at startup." >&2
    exit 1
fi
rm -f "${DATA_DIR}/.write-test"

if [ -f "${SECRETS_FILE}" ]; then
    # Source the secrets file and export every variable it defines
    # so they are visible to the application process.
    set -a
    # shellcheck disable=SC1090
    . "${SECRETS_FILE}"
    set +a
fi

export PORT="${PORT:-8088}"

# uvicorn port/entrypoint can be overridden via CMD args by the image default.
if [ "$#" -eq 0 ]; then
    set -- python -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}"
fi

exec "$@"
