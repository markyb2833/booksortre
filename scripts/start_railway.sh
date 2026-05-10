#!/usr/bin/env sh
set -eu

APP_DIR="${APP_DIR:-$(pwd)}"
INSTANCE_DIR="${BOOKSORT_INSTANCE_PATH:-${RAILWAY_VOLUME_MOUNT_PATH:-$APP_DIR/instance}}"
DB_PATH="$INSTANCE_DIR/booksort.db"
SEED_DB="$APP_DIR/seed/booksort.seed.db"

if [ -z "${DATABASE_URL:-}" ]; then
    mkdir -p "$INSTANCE_DIR"
    export BOOKSORT_INSTANCE_PATH="$INSTANCE_DIR"

    if [ ! -f "$DB_PATH" ] && [ -f "$SEED_DB" ]; then
        cp "$SEED_DB" "$DB_PATH"
        echo "Seeded SQLite database at $DB_PATH"
    fi
fi

exec gunicorn \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    wsgi:app
