#!/bin/sh
# Starts the API as an unprivileged user. If a platform mounts a root-owned disk
# (e.g. a Render persistent disk), fix ownership first, then drop privileges.
set -e
DATA="${DATA_DIR:-/app/data}"
UPLOADS="${UPLOAD_DIR:-/app/data/uploads}"
mkdir -p "$DATA" "$UPLOADS"

CMD="exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"

if [ "$(id -u)" = "0" ]; then
  chown -R app:app "$DATA" "$UPLOADS" 2>/dev/null || true
  exec su -s /bin/sh app -c "$CMD"
fi
exec sh -c "$CMD"
