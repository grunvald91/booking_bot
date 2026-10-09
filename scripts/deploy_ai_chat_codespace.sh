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
MANIFEST="docs/ai-chat-production-baseline-20261009.json"
REFERENCE="${SERVGO_REVIEWED_FRONTEND_REFERENCE:-}"
[[ -n "$REFERENCE" ]] || { echo "Set SERVGO_REVIEWED_FRONTEND_REFERENCE to the audited prior frontend sources." >&2; exit 1; }
FILES=(
  web/api/sales/engine.py web/api/sales/provider.py
  web/api/sales/stages.py web/api/sales/state.py
  web/api/routes/ai.py web/api/schemas.py datetime_utils.py
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
  wanted="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["backend"][sys.argv[2]])' "$MANIFEST" "$p")"
  actual="$(ssh "${OPT[@]}" "$TARGET" "sha256sum '${REMOTE}/${p}'" 2>/dev/null | cut -d' ' -f1)" || deny "Missing production file $p."
  [[ "$wanted" == "$actual" ]] || deny "$p has changed on server or the initial sales-agent release is absent; manual reconciliation is required."
done
ssh "${OPT[@]}" "$TARGET" "systemctl is-active --quiet '$SERVICE' && test -f '$REMOTE/web/frontend/dist/index.html'" || deny "Production API or frontend location differs."

# Tests run in Codespace with synthetic data, never against production PostgreSQL.
LOCAL_TMP="$(mktemp -d)"
cleanup() { git worktree remove --force "$LOCAL_TMP/base" >/dev/null 2>&1 || true; rm -rf "$LOCAL_TMP"; }
trap cleanup EXIT
if [[ -n "${SERVGO_TEST_PYTHON:-}" ]]; then
  TEST_PYTHON="$SERVGO_TEST_PYTHON"
else
  python3 -m venv "$LOCAL_TMP/venv"
  "$LOCAL_TMP/venv/bin/pip" install -q --disable-pip-version-check -r requirements.txt -r web/api/requirements.txt pytest aiosqlite python-multipart
  TEST_PYTHON="$LOCAL_TMP/venv/bin/python"
fi
env -u SERVGO_SALES_TEST_POSTGRES_URL BOT_TOKEN=test-token DATABASE_URL='sqlite+aiosqlite:///:memory:' \
  "$TEST_PYTHON" -m pytest -q tests/test_sales_agent.py tests/test_email_auth_and_payments.py || deny "Tests failed. No files were sent."
python3 -m py_compile "${FILES[@]}"
(cd web/frontend && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build) || deny "Frontend build failed. No files were sent."

# Ensure replacing dist cannot accidentally discard unrelated deployed frontend work.
python3 scripts/verify_ai_chat_release.py reference "$MANIFEST" "$REFERENCE" "$LOCAL_TMP/base/web/frontend" || deny "Reference source provenance differs."
(cd "$LOCAL_TMP/base/web/frontend" && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build) || deny "Reference frontend build failed."
python3 scripts/verify_ai_chat_release.py dist "$MANIFEST" "$LOCAL_TMP/base/web/frontend/dist" || deny "Reference build differs from deployed frontend."
wanted_dist="$(python3 -c 'import hashlib,json,sys; m=json.load(open(sys.argv[1]))["frontend_dist"]; print(hashlib.sha256("".join(m[p]+"  ./"+p+"\n" for p in sorted(m)).encode()).hexdigest())' "$MANIFEST")"
verify_server_baseline() {
  for p in "${FILES[@]}"; do
    wanted="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["backend"][sys.argv[2]])' "$MANIFEST" "$p")"
    actual="$(ssh "${OPT[@]}" "$TARGET" "sha256sum '${REMOTE}/${p}'" | cut -d' ' -f1)" || return 1
    [[ "$wanted" == "$actual" ]] || return 1
  done
  actual_dist="$(ssh "${OPT[@]}" "$TARGET" "cd '$REMOTE/web/frontend/dist' && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1")" || return 1
  [[ "$wanted_dist" == "$actual_dist" ]]
}
verify_server_baseline || deny "Production changed after the reviewed audit."

# Never print production environment variables, credentials or session data.
ssh "${OPT[@]}" "$TARGET" "python3 - '$SERVICE' <<'PY'
import pathlib, subprocess, sys
pid = subprocess.check_output(['systemctl', 'show', sys.argv[1], '--property=MainPID', '--value'], text=True).strip()
if not pid.isdigit() or int(pid) < 2: sys.exit('Web API not running')
env = dict(item.split(b'=', 1) for item in pathlib.Path('/proc/' + pid + '/environ').read_bytes().split(b'\0') if b'=' in item)
chat_model = env.get(b'CLAUDEHUB_CHAT_MODEL', b'')
chat_format = env.get(b'CLAUDEHUB_CHAT_API_FORMAT', b'')
if chat_format and chat_format != b'openai': sys.exit('Existing AI API format override needs review')
if chat_model and chat_model != b'gpt-6-luna': sys.exit('Existing AI model override needs review')
if not env.get(b'CLAUDEHUB_BASE_URL') or not env.get(b'CLAUDEHUB_API_KEY'): sys.exit('ClaudeHub credentials not configured for API')
print('Runtime model configuration: verified without exposing values')
PY" || deny "API environment preflight failed."

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$REMOTE/.releases/ai-chat-before-$stamp.tar.gz"
payload="$LOCAL_TMP/payload.tar.gz"
tar -czf "$payload" "${FILES[@]}" web/frontend/dist || deny "Unable to package scoped changes."
ssh "${OPT[@]}" "$TARGET" "mkdir -p '$REMOTE/.releases' && chmod 700 '$REMOTE/.releases' && cd '$REMOTE' && tar -czf '$backup' ${FILES[*]} web/frontend/dist && gzip -t '$backup' && chmod 600 '$backup'" || deny "Server backup failed. No upload done."
scp "${OPT[@]}" "$payload" "$TARGET:/tmp/servgo-ai-chat-$stamp.tar.gz" || deny "Unable to upload package."

rollback() {
  echo "Deploy failed: attempting rollback of API + frontend." >&2
  if ssh "${OPT[@]}" "$TARGET" "cd '$REMOTE' && rm -rf web/frontend/dist && tar -xzf '$backup' && systemctl restart '$SERVICE'"; then
    for attempt in {1..10}; do
      if ssh "${OPT[@]}" "$TARGET" "systemctl is-active --quiet '$SERVICE' && curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null" && verify_server_baseline; then
        echo "ROLLBACK VERIFIED: original API files and frontend restored." >&2
        deny "Deployment rolled back. Backup: $backup"
      fi
      sleep 2
    done
  fi
  echo "ROLLBACK NOT VERIFIED: operator recovery required using $backup" >&2
  deny "Deployment not confirmed. Server backup: $backup"
}
ssh "${OPT[@]}" "$TARGET" "set -e; cd '$REMOTE'; stage='$REMOTE/.releases/ai-chat-stage-$stamp'; mkdir -p \"\$stage\"; tar -xzf '/tmp/servgo-ai-chat-$stamp.tar.gz' -C \"\$stage\"; cp -an web/frontend/dist/assets/. \"\$stage/web/frontend/dist/assets/\"; for p in ${FILES[*]}; do cp \"\$stage/\$p\" \"\$p\"; done; mv web/frontend/dist \"\$stage/previous-dist\"; mv \"\$stage/web/frontend/dist\" web/frontend/dist; rm -f '/tmp/servgo-ai-chat-$stamp.tar.gz'; systemctl restart '$SERVICE'" || rollback
ssh "${OPT[@]}" "$TARGET" "systemctl is-active --quiet '$SERVICE' && for attempt in 1 2 3 4 5 6 7 8 9 10; do if curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null && curl -fsS --max-time 3 http://127.0.0.1:8000/openapi.json | python3 -c 'import json,sys; paths=json.load(sys.stdin)[\"paths\"]; assert \"/ai/chat\" in paths and \"/ai/select-slot\" in paths'; then exit 0; fi; sleep 2; done; exit 1" || rollback

curl -fsS --max-time 15 https://servgo.ru/ > "$LOCAL_TMP/public-index.html" || rollback
cmp -s "$LOCAL_TMP/public-index.html" web/frontend/dist/index.html || rollback
ssh "${OPT[@]}" "$TARGET" "python3 - '$SERVICE' <<'PY'
import json, pathlib, subprocess, sys, time, urllib.request, urllib.error
pid = subprocess.check_output(['systemctl', 'show', sys.argv[1], '--property=MainPID', '--value'], text=True).strip()
env = dict(item.split(b'=', 1) for item in pathlib.Path('/proc/' + pid + '/environ').read_bytes().split(b'\\0') if b'=' in item)
model = env.get(b'CLAUDEHUB_CHAT_MODEL', b'gpt-6-luna').decode() or 'gpt-6-luna'
assert model == 'gpt-6-luna', 'Unexpected chat model'
url = env[b'CLAUDEHUB_BASE_URL'].decode().rstrip('/') + '/chat/completions'
payload = {'model': model, 'messages': [{'role': 'user', 'content': 'Call release_probe with ok=true.'}], 'reasoning_effort': 'none', 'max_completion_tokens': 200, 'tools': [{'type': 'function', 'function': {'name': 'release_probe', 'description': 'Harmless deployment test.', 'parameters': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}}}], 'tool_choice': 'required'}
req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env[b'CLAUDEHUB_API_KEY'].decode()})
start=time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=40) as response:
        data=json.load(response)
    calls=data['choices'][0]['message'].get('tool_calls') or []
    assert calls and calls[0]['function']['name']=='release_probe'
    assert json.loads(calls[0]['function']['arguments'])['ok'] is True
except urllib.error.HTTPError as exc:
    sys.exit('Model probe HTTP status: '+str(exc.code))
print('GPT-6 Luna function calling VERIFIED; seconds:',round(time.monotonic()-start,2))
PY" || rollback
echo "SUCCESS: only the AI booking backend files and React dist were deployed."
echo "Server rollback archive: $backup"
