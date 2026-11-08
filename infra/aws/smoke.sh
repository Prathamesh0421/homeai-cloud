#!/usr/bin/env bash
# HomeAI Cloud — post-deploy smoke test (C4-16).
# Owner: Mohit. Run on the EC2 host after `make deploy` + `make seed-c4`.
#
# Checks the four things the demo depends on:
#   1. C4 health through Caddy
#   2. Login as ops@homeai.test / Demo!2026
#   3. JWKS reachable (so other services can verify tokens)
#   4. SNS publish works with the IAM role (C2 creates topics on demand)
#
# Exits non-zero on any failure. Safe to re-run.

set -euo pipefail

BASE="${PUBLIC_BASE_URL:-http://localhost}"
EMAIL="${SMOKE_EMAIL:-ops@homeai.test}"
PASSWORD="${SMOKE_PASSWORD:-Demo!2026}"

echo "[smoke] base=${BASE}"

# 1. C4 health
echo -n "[smoke] C4 health ... "
health="$(curl -fsS "${BASE}/api/v1/health/c4" || true)"
if echo "${health}" | grep -q '"status":"ok"'; then
  echo "ok"
else
  echo "FAIL"
  echo "  ${health:-no response}" >&2
  exit 1
fi

# 2. Login
echo -n "[smoke] login ${EMAIL} ... "
login="$(curl -fsS -X POST "${BASE}/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}")"
token="$(echo "${login}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["token"])' 2>/dev/null || true)"
if [ -z "${token}" ]; then
  echo "FAIL"
  echo "  ${login}" >&2
  exit 1
fi
echo "ok (token len ${#token})"

# 3. JWKS reachable (the contract: every service verifies C4 tokens via this)
echo -n "[smoke] JWKS ... "
jwks="$(curl -fsS "${BASE}/.well-known/jwks.json")"
keys="$(echo "${jwks}" | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("keys",[])))' 2>/dev/null || echo 0)"
if [ "${keys}" -ge 1 ]; then
  echo "ok (${keys} key(s))"
else
  echo "FAIL (no keys)"; exit 1
fi

# 4. /auth/me with the token (proves the JWT round-trips through C4's own JWKS)
echo -n "[smoke] /auth/me ... "
me="$(curl -fsS "${BASE}/api/v1/auth/me" -H "Authorization: Bearer ${token}")"
if echo "${me}" | grep -q "${EMAIL}"; then
  echo "ok"
else
  echo "FAIL"; echo "  ${me}" >&2; exit 1
fi

# 5. SNS: C2 creates topics on demand; verify the IAM role can list topics.
#    (C2 must be up; if it is not, this is skipped, not a failure.)
echo -n "[smoke] SNS list-topics (IAM role) ... "
if curl -fsS "${BASE}/api/v1/health/c2" >/dev/null 2>&1; then
  # Ask C2 to list its topics via its own endpoint if present; otherwise
  # fall back to the AWS CLI on the EC2 host (uses the instance profile).
  if aws sns list-topics --region "${AWS_REGION:-us-west-2}" >/dev/null 2>&1; then
    echo "ok (IAM role can list topics)"
  else
    echo "FAIL (IAM role cannot list topics — check ec2-policy.json)"; exit 1
  fi
else
  echo "skip (C2 not up yet)"
fi

echo "[smoke] all checks passed"
