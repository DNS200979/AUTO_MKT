#!/usr/bin/env bash
set -Eeuo pipefail

backup_file="${1:?usage: upload_backup_r2.sh BACKUP.dump}"
r2_endpoint="${R2_ENDPOINT:?R2_ENDPOINT must be set}"
r2_bucket="${R2_BUCKET:?R2_BUCKET must be set}"
age_recipient="${AGE_RECIPIENT:?AGE_RECIPIENT must be set}"

[[ -f "$backup_file" ]] || { printf 'backup not found: %s\n' "$backup_file" >&2; exit 2; }
command -v age >/dev/null || { printf 'age is required\n' >&2; exit 2; }
command -v aws >/dev/null || { printf 'aws CLI is required\n' >&2; exit 2; }

umask 077
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/market-r2.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

encrypted="$tmp_dir/$(basename "$backup_file").age"
age --recipient "$age_recipient" --output "$encrypted" "$backup_file"
sha256sum -- "$encrypted" >"$encrypted.sha256"

object_prefix="${R2_PREFIX:-market-backups}/$(date -u +%Y/%m/%d)"
aws --endpoint-url "$r2_endpoint" s3 cp "$encrypted" \
  "s3://$r2_bucket/$object_prefix/$(basename "$encrypted")" \
  --no-progress
aws --endpoint-url "$r2_endpoint" s3 cp "$encrypted.sha256" \
  "s3://$r2_bucket/$object_prefix/$(basename "$encrypted.sha256")" \
  --no-progress
printf 'uploaded_prefix=%s\n' "$object_prefix"
