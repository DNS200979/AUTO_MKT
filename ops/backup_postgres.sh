#!/usr/bin/env bash
set -Eeuo pipefail

database_url="${MARKET_DATABASE_URL:?MARKET_DATABASE_URL must be set}"
backup_dir="${BACKUP_DIR:-./backups}"
label="${BACKUP_LABEL:-market-$(date -u +%Y%m%dT%H%M%SZ)}"

umask 077
mkdir -p -- "$backup_dir"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/market-backup.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

archive_tmp="$tmp_dir/$label.dump"
archive="$backup_dir/$label.dump"
manifest="$backup_dir/$label.sha256"

pg_dump --format=custom --no-owner --no-privileges --file="$archive_tmp" "$database_url"
mv -- "$archive_tmp" "$archive"
sha256sum -- "$archive" >"$manifest"
printf 'backup=%s\nmanifest=%s\n' "$archive" "$manifest"
