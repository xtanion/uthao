#!/usr/bin/env bash
# Push the secrets fihy needs from a local .env into Fly.
#
#   ./scripts/fly-secrets.sh [path-to-env]
#
# The allowlist is deliberate rather than "everything in .env". Two settings in
# particular must never reach production: OTP_DEBUG_CODE accepts one code for
# every phone number, and a development SECRET_KEY makes every token forgeable.
# The app refuses to boot on either, but not shipping them is the better guard.
set -euo pipefail

ENV_FILE="${1:-.env}"
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE" >&2; exit 1; }

ALLOWED=(
  SECRET_KEY
  DATABASE_URL
  PUBLIC_BASE_URL
  R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET
  ANTHROPIC_API_KEY
  MAIL_FROM_DOMAIN MAIL_REPLY_DOMAIN MAIL_FROM_NAME AUTHORITY_EMAIL
  SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD
  INBOUND_MAIL_SECRET
)

staged=$(mktemp) && trap 'rm -f "$staged"' EXIT
sent=()
for key in "${ALLOWED[@]}"; do
  line=$(grep -E "^${key}=" "$ENV_FILE" || true)
  value="${line#*=}"
  [ -n "$line" ] && [ -n "$value" ] || continue
  printf '%s\n' "$line" >> "$staged"
  sent+=("$key")
done

[ "${#sent[@]}" -gt 0 ] || { echo "nothing to send from $ENV_FILE" >&2; exit 1; }

case " ${sent[*]} " in
  *" SECRET_KEY "*)
    if grep -q '^SECRET_KEY=development-only' "$ENV_FILE"; then
      echo "SECRET_KEY is still the development default. Generate one:" >&2
      echo "  openssl rand -hex 32" >&2
      exit 1
    fi ;;
esac

# Names only. The values go to Fly over stdin and are never printed.
printf 'sending %d secret(s): %s\n' "${#sent[@]}" "${sent[*]}"
fly secrets import --stage < "$staged"
echo
echo "Staged. They apply on the next deploy:  fly deploy"
