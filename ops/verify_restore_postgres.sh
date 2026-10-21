#!/usr/bin/env bash
set -Eeuo pipefail

archive="${1:?usage: verify_restore_postgres.sh BACKUP.dump TARGET_DATABASE_URL}"
target_url="${2:?usage: verify_restore_postgres.sh BACKUP.dump TARGET_DATABASE_URL}"
manifest="${archive%.dump}.sha256"

[[ -f "$archive" ]] || { printf 'backup not found: %s\n' "$archive" >&2; exit 2; }
[[ -f "$manifest" ]] || { printf 'manifest not found: %s\n' "$manifest" >&2; exit 2; }
sha256sum --check "$manifest"
pg_restore --list "$archive" >/dev/null

if [[ "${ALLOW_DESTRUCTIVE_RESTORE:-}" == "YES" ]]; then
  restore_flags=(--clean --if-exists)
else
  restore_flags=()
  printf 'restoring without --clean; target must be disposable or empty\n' >&2
fi

pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
  "${restore_flags[@]}" --dbname="$target_url" "$archive"
psql "$target_url" --command='SELECT 1' >/dev/null
printf 'restore verification passed for %s\n' "$archive"
