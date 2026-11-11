#!/bin/sh
# Entrypoint: optionally source DATA_DIR/secrets.env, then start uvicorn.
set -eu

DATA_DIR="${DATA_DIR:-/data}"
SECRETS_FILE="${DATA_DIR}/secrets.env"

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
