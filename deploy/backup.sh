#!/usr/bin/env bash
# 每日 SQLite 备份，保留 7 天。加到 cron：0 4 * * * /opt/whu-notice-hub/deploy/backup.sh
set -euo pipefail

ROOT="${ROOT:-/opt/whu-notice-hub}"
DB="${DB_PATH:-$ROOT/data/app.db}"
DEST="${BACKUP_DIR:-$ROOT/data/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"

mkdir -p "$DEST"
STAMP=$(date +%Y%m%d)
OUT="$DEST/app-$STAMP.db"

"$ROOT/.venv/bin/python" - "$DB" "$OUT" <<'PY'
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY

find "$DEST" -name 'app-*.db' -mtime "+$KEEP_DAYS" -delete
echo "$(date '+%F %T') backup ok: $OUT"
