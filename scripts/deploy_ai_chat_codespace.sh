#!/usr/bin/env bash
# ServGo AI chat: scoped Codespace -> production release.
# Must be run from an authorized GitHub Codespace. Never uses GitHub Actions.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TARGET="${SERVGO_DEPLOY_SSH:-root@155.212.162.47}"
REMOTE="/opt/booking_bot"
SERVICE="${SERVGO_API_SERVICE:-booking-web-api}"
BASE="9933f26beed590247e4305a61e34f08681a5e2dd"
BRANCH="fix/ai-booking-chat-ux-20261008"
FILES=(
  web/api/sales/engine.py web/api/sales/provider.py
  web/api/sales/stages.py web/api/sales/state.py
  web/api/routes/ai.py web/api/schemas.py
)
deny() { echo "STOP: $*" >&2; exit 1; }
[[ "$(git branch --show-current)" == "$BRANCH" ]] || deny "Choose branch $BRANCH."
[[ -z "$(git status --porcelain)" ]] || deny "Working tree contains uncommitted changes."
git cat-file -e "${BASE}^{commit}" || deny "Base commit is unavailable; fetch the feature branch."
command -v ssh && command -v scp && command -v python3 && command -v npm >/dev/null || deny "Codespace needs ssh, scp, Python and npm."
OPT=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8)
ssh "${OPT[@]}" "$TARGET" true || deny "Existing SSH key or trusted host is unavailable."

echo "Preflight: checking server-side sales-agent baseline (no overwrites yet)"
for p in "${FILES[@]}"; do
  wanted="$(git show "${BASE}:${p}" | sha256sum | cut -d' ' -f1)"
  actual="$(ssh "${OPT[@]}" "$TARGET" "sha256sum '${REMOTE}/${p}'" 2>/dev/null | cut -d' ' -f1)" || deny "Missing production file $p."
  [[ "$wanted" == "$actual" ]] || deny "$p has changed on server or the initial sales-agent release is absent; manual reconciliation is required."
done
ssh "${OPT[@]}" "$TARGET" "systemctl is-active --quiet '$SERVICE' && test -f '$REMOTE/web/frontend/dist/index.html'" || deny "Production API or frontend location differs."

# Tests run in Codespace with synthetic data, never against production PostgreSQL.
LOCAL_TMP="$(mktemp -d)"
cleanup() { git worktree remove --force "$LOCAL_TMP/base" >/dev/null 2>&1 || true; rm -rf "$LOCAL_TMP"; }
trap cleanup EXIT
python3 -m venv "$LOCAL_TMP/venv"
"$LOCAL_TMP/venv/bin/pip" install -q --disable-pip-version-check -r requirements.txt -r web/api/requirements.txt pytest aiosqlite python-multipart
env -u SERVGO_SALES_TEST_POSTGRES_URL BOT_TOKEN=test-token DATABASE_URL='sqlite+aiosqlite:///:memory:' \
  "$LOCAL_TMP/venv/bin/python" -m pytest -q tests/test_sales_agent.py || deny "Tests failed. No files were sent."
python3 -m py_compile "${FILES[@]}"
(cd web/frontend && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build) || deny "Frontend build failed. No files were sent."

# Ensure replacing dist cannot accidentally discard unrelated deployed frontend work.
git worktree add --detach "$LOCAL_TMP/base" "$BASE" >/dev/null || deny "Could not prepare reference frontend."
(cd "$LOCAL_TMP/base/web/frontend" && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build) || deny "Reference frontend build failed."
wanted_dist="$(cd "$LOCAL_TMP/base/web/frontend/dist" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
actual_dist="$(ssh "${OPT[@]}" "$TARGET" "cd '$REMOTE/web/frontend/dist' && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1")" || deny "Could not verify production frontend."
[[ "$wanted_dist" == "$actual_dist" ]] || deny "Deployed frontend differs from the reviewed baseline; refusing to replace it."

# Never print production environment variables, credentials or session data.
ssh "${OPT[@]}" "$TARGET" "python3 - '$SERVICE' <<'PY'
import pathlib, subprocess, sys
pid = subprocess.check_output(['systemctl', 'show', sys.argv[1], '--property=MainPID', '--value'], text=True).strip()
if not pid.isdigit() or int(pid) < 2: sys.exit('Web API not running')
env = dict(item.split(b'=', 1) for item in pathlib.Path('/proc/' + pid + '/environ').read_bytes().split(b'\\0') if b'=' in item)
chat_model = env.get(b'CLAUDEHUB_CHAT_MODEL', b'')
if chat_model and chat_model != b'gpt-6-luna': sys.exit('Existing AI model override needs review')
if not env.get(b'CLAUDEHUB_BASE_URL') or not env.get(b'CLAUDEHUB_API_KEY'): sys.exit('ClaudeHub credentials not configured for API')
print('Runtime model configuration: verified without exposing values')
PY" || deny "API environment preflight failed."

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$REMOTE/.releases/ai-chat-before-$stamp.tar.gz"
payload="$LOCAL_TMP/payload.tar.gz"
tar -czf "$payload" "${FILES[@]}" web/frontend/dist || deny "Unable to package scoped changes."
ssh "${OPT[@]}" "$TARGET" "mkdir -p '$REMOTE/.releases' && chmod 700 '$REMOTE/.releases' && cd '$REMOTE' && tar -czf '$backup' ${FILES[*]} web/frontend/dist && chmod 600 '$backup'" || deny "Server backup failed. No upload done."
scp "${OPT[@]}" "$payload" "$TARGET:/tmp/servgo-ai-chat-$stamp.tar.gz" || deny "Unable to upload package."

rollback() {
  echo "Deploy failed: attempting rollback of API + frontend." >&2
  ssh "${OPT[@]}" "$TARGET" "cd '$REMOTE' && rm -rf web/frontend/dist && tar -xzf '$backup' && systemctl restart '$SERVICE'" || true
  deny "Deployment not confirmed. Server backup: $backup"
}
ssh "${OPT[@]}" "$TARGET" "cd '$REMOTE' && rm -rf web/frontend/dist && tar -xzf '/tmp/servgo-ai-chat-$stamp.tar.gz' && rm -f '/tmp/servgo-ai-chat-$stamp.tar.gz' && systemctl restart '$SERVICE'" || rollback
ssh "${OPT[@]}" "$TARGET" "systemctl is-active --quiet '$SERVICE' && for attempt in 1 2 3 4 5 6 7 8 9 10; do if curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null && curl -fsS --max-time 3 http://127.0.0.1:8000/openapi.json | python3 -c 'import json,sys; paths=json.load(sys.stdin)[\"paths\"]; assert \"/ai/chat\" in paths and \"/ai/select-slot\" in paths'; then exit 0; fi; sleep 2; done; exit 1" || rollback

echo "SUCCESS: only the AI booking backend files and React dist were deployed."
echo "Server rollback archive: $backup"
