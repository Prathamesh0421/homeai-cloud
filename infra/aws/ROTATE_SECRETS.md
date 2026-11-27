# A-0 — Rotate secrets before the ALB goes public

The repo is public. Dev service-client secrets (`dev-c2-secret`, …) and the demo
password `Demo!2026` are known. **Rotate them on AWS before** pointing DuckDNS at
the ALB (`docs/08` A-0). This checklist is **manual** (no live rotation from CI).

Region: `us-west-2`. Adjust `REGION` / account as needed.

## 0. Prerequisites

- `aws` CLI configured as Mohit (admin).
- Ability to reach RDS (SSH tunnel to the legacy EC2, or a bastion, or temporary
  `0.0.0.0/0` **never** leave that open).
- `jq`, `python3`, `bcrypt` (`pip install bcrypt`) on the machine that hashes.

```bash
export REGION=us-west-2
export TEAM=cmpe281
```

## 1. Generate new service-client secrets

```bash
# Alphanumeric; keep a local copy in a password manager — not in git.
NEW_C2=$(openssl rand -hex 24)
NEW_C3=$(openssl rand -hex 24)
NEW_C4=$(openssl rand -hex 24)
NEW_DEVICE=$(openssl rand -hex 24)

CLIENTS_JSON=$(jq -n \
  --arg c2 "$NEW_C2" --arg c3 "$NEW_C3" --arg c4 "$NEW_C4" --arg dev "$NEW_DEVICE" \
  '{"c2-alerts":$c2,"c3-data":$c3,"c3-worker":$c3,"c4-dashboard":$c4,"device-uploader":$dev}')

echo "$CLIENTS_JSON"   # sanity-check keys only; do not paste into Slack/PRs
```

## 2. Put the new JSON into Secrets Manager

```bash
aws secretsmanager put-secret-value \
  --region "$REGION" \
  --secret-id homeai/service-clients \
  --secret-string "$CLIENTS_JSON"
```

Confirm the new version is current:

```bash
aws secretsmanager get-secret-value \
  --region "$REGION" \
  --secret-id homeai/service-clients \
  --query VersionId --output text
```

## 3. Re-hash `c4.service_clients` (and refresh the host `.env`)

C4 stores **bcrypt hashes**, not the plaintext. The seed upserts `secret_hash` from
`SERVICE_CLIENT_SECRET_*` env vars (see `services/c4_dashboard/app/seed.py`).

On the running host (legacy EC2 or an API instance) after regenerating `.env`:

```bash
# On the EC2 host:
cd ~/homeai-cloud
RDS_ENDPOINT=<rds-host>:5432 TEAM=cmpe281 \
  SITE_ADDRESS=:80 PUBLIC_BASE_URL=https://homeai.duckdns.org \
  make deploy-env > .env

# Ensure the new secrets are in the container environment, then:
make seed-c4-docker
# or: docker compose … exec c4-dashboard python -m app.seed
```

`seed` updates existing service-client rows' `secret_hash`. It does **not** rotate
user passwords on existing rows (see step 4).

If you cannot re-seed, update hashes with SQL (example for one client):

```bash
HASH=$(python3 -c "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())" "$NEW_C3")
# Then as c4_app / master against RDS:
# UPDATE c4.service_clients SET secret_hash = '<HASH>' WHERE client_id = 'c3-worker';
```

## 4. Rotate the demo user password

Pick a new password (store offline). Generate a bcrypt hash:

```bash
export NEW_DEMO_PASSWORD='…'   # not Demo!2026
HASH=$(python3 -c "import bcrypt,os; print(bcrypt.hashpw(os.environ['NEW_DEMO_PASSWORD'].encode(), bcrypt.gensalt()).decode())")
```

Apply to every seeded user (adjust host/user):

```bash
PGPASSWORD="$(aws secretsmanager get-secret-value --secret-id homeai/db/master \
  --query SecretString --output text --region "$REGION")" \
psql -h <rds-endpoint> -U postgres -d homeai <<SQL
UPDATE c4.users
SET password_hash = '${HASH}',
    failed_login_count = 0,
    locked_until = NULL
WHERE email IN (
  'ops@homeai.test',
  'iot@acme.test',
  'owner.maple@acme.test',
  'owner.oak@acme.test',
  'owner.sun@sunrise.test'
);
SQL
```

Share the new password with the team out-of-band for the 2 Dec rehearsal only.

## 5. Set `DEMO_MODE=0` outside the live demo window

On every host `.env` / `homeai/runtime-env`:

```bash
# Prefer a dedicated runtime secret for ASG user-data:
#   aws secretsmanager put-secret-value --secret-id homeai/runtime-env --secret-string file://.env
sed -i 's/^DEMO_MODE=.*/DEMO_MODE=0/' .env
# Recreate containers so they pick it up:
#   docker compose … up -d
```

For the **presentation only**, set `DEMO_MODE=1` again (C2 `view_link`, fixed seed
`house_id`, etc.), then flip back to `0` afterward.

## 6. Verify old secrets fail

Service-client mint path is `POST /api/v1/auth/service-token` (contracts / C4).

```bash
BASE="${BASE_URL:-https://homeai.duckdns.org}"

# Old service client must be 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/v1/auth/service-token" \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"c3-worker","client_secret":"dev-c3-secret"}'
# expect 401

# New secret must be 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/v1/auth/service-token" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"c3-worker\",\"client_secret\":\"$NEW_C3\"}"
# expect 200

# Old demo password must fail
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"ops@homeai.test","password":"Demo!2026"}'
# expect 401

# New password must succeed
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"ops@homeai.test\",\"password\":\"$NEW_DEMO_PASSWORD\"}"
# expect 200
```

Against the legacy single-EC2 stack, substitute `http://<eip>` or the DuckDNS name
still pointing at the EIP.

## 7. Done when

- [ ] `homeai/service-clients` version is new (not the provision.sh bootstrap JSON).
- [ ] `c4.service_clients.secret_hash` verifies only the new plaintext.
- [ ] Demo user logins reject `Demo!2026`.
- [ ] `DEMO_MODE=0` on AWS except during the scheduled demo window.
- [ ] Old client secrets return 401 from `/api/v1/auth/service-token`.

Do **not** commit the new secrets, hashes, or a filled `terraform.tfvars`.
