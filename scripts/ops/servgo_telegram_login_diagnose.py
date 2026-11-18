#!/usr/bin/env python3
"""Read-only ServGo Telegram login diagnostics. Never print tokens or user payloads."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import urllib.error


def remote_source() -> str:
    return r'''
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

EXPECTED_WIDGET_BOT = "sochiservice_bot"

def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""

def unit(name):
    status, out = run(["systemctl", "show", name, "-p", "MainPID", "-p", "ActiveState", "-p", "SubState", "-p", "ExecMainStatus"])
    data = dict(part.split("=", 1) for part in out.splitlines() if "=" in part)
    try:
        pid = int(data.get("MainPID", "0"))
    except ValueError:
        pid = 0
    env = {}
    if pid > 0:
        try:
            entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            for item in entries:
                if b"=" in item:
                    k, v = item.split(b"=", 1)
                    env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        except OSError:
            pass
    print("UNIT", name, "active=" + data.get("ActiveState", "unknown"), "env_readable=" + str(bool(env)))
    print("AUTH_ENV", name,
          "BOT_TOKEN=" + ("present" if env.get("BOT_TOKEN") else "missing"),
          "TELEGRAM_LOGIN_BOT_TOKEN=" + ("present" if env.get("TELEGRAM_LOGIN_BOT_TOKEN") else "missing"),
          "BOT_USERNAME=" + (env.get("BOT_USERNAME", "").lstrip("@").lower() or "unset"))
    return env

api = unit("booking-web-api.service")
bot = unit("booking-bot.service")
api_token = api.get("TELEGRAM_LOGIN_BOT_TOKEN") or api.get("BOT_TOKEN")
bot_token = bot.get("BOT_TOKEN")
if api_token and bot_token:
    print("API_AND_BOT_TOKENS_MATCH", api_token == bot_token)
else:
    print("API_AND_BOT_TOKENS_MATCH", "unknown")
if api_token:
    try:
        # Send token ONLY to official Telegram API, never to logs.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request("https://api.telegram.org/bot" + api_token + "/getMe")
        with opener.open(request, timeout=7) as response:
            payload = json.load(response)
        username = str((payload.get("result") or {}).get("username") or "").lower()
        print("TELEGRAM_GETME_STATUS", "ok" if payload.get("ok") else "not_ok")
        print("LOGIN_TOKEN_MATCHES_WIDGET_BOT", username == EXPECTED_WIDGET_BOT)
        print("ACTIVE_BOT_USERNAME", username or "unknown")
    except Exception as exc:
        # Exceptions can include URLs containing credentials: print type only.
        print("TELEGRAM_GETME_STATUS", "unavailable_" + type(exc).__name__)
else:
    print("TELEGRAM_GETME_STATUS", "token_not_found")

# Compare against an existing local .env file without exposing tokens.
for filename in ("/opt/booking_bot/.env", "/opt/booking_bot/.env.production"):
    f = Path(filename)
    if not f.is_file():
        print("BOT_TOKEN_SOURCE", filename, "not_found")
        continue
    candidate = ""
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line.startswith("BOT_TOKEN="):
            candidate = line.split("=", 1)[1].strip().strip("'").strip('"')
            break
    print("BOT_TOKEN_SOURCE", filename, "present" if candidate else "empty")
    if candidate:
        print("API_MATCHES_LOCAL_BOT_TOKEN", filename, api_token == candidate)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request("https://api.telegram.org/bot" + candidate + "/getMe")
            with opener.open(request, timeout=7) as response:
                result = json.load(response)
            username = str((result.get("result") or {}).get("username") or "").lower()
            print("LOCAL_BOT_TOKEN_MATCHES_WIDGET", filename, username == EXPECTED_WIDGET_BOT)
        except Exception as exc:
            print("LOCAL_BOT_TOKEN_GETME_STATUS", filename, "unavailable_" + type(exc).__name__)

utc = datetime.datetime.now(datetime.timezone.utc)
print("SERVER_UTC", utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
_, ntp = run(["timedatectl", "show", "-p", "NTPSynchronized"])
print("CLOCK_SYNC", (ntp.strip() or "unknown"))
file = Path("/opt/booking_bot/web/api/routes/auth.py")
print("API_AUTH_FILE_PRESENT", file.is_file())
if file.is_file():
    print("API_AUTH_FILE_SHA256", hashlib.sha256(file.read_bytes()).hexdigest())
rc, logs = run(["journalctl", "-u", "booking-web-api.service", "--since", "-2 hours", "-n", "500", "--no-pager", "-o", "cat"])
print("API_AUTH_ERROR_LINES_LAST_2H", sum("Invalid Telegram auth payload" in line for line in logs.splitlines()) if rc == 0 else "unavailable")
'''

def main() -> None:
    import paramiko

    password = os.getenv("SERVER_SSH_PASSWORD", "")
    if not password:
        raise SystemExit("Missing SERVER_SSH_PASSWORD")
    host = os.getenv("SERVER_HOST", "155.212.162.47")
    port = int(os.getenv("SERVER_PORT", "22"))
    user = os.getenv("SERVER_USER", "root")
    expected = "uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU"

    class Pinned(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            if fp != expected:
                raise paramiko.SSHException("Pinned production SSH host key mismatch")
            client.get_host_keys().add(hostname, key.get_name(), key)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(Pinned())
    try:
        client.connect(hostname=host, port=port, username=user, password=password,
                       look_for_keys=False, allow_agent=False, timeout=12, auth_timeout=12, banner_timeout=15)
        source = base64.b64encode(remote_source().encode()).decode()
        command = "python3 -c 'import base64;exec(base64.b64decode(\"" + source + "\"))'"
        _, stdout, stderr = client.exec_command(command, timeout=35)
        output = stdout.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if code:
            raise RuntimeError("Server diagnostic failed; remote error deliberately suppressed")
        print(output)
        repo_hash = hashlib.sha256(Path("web/api/routes/auth.py").read_bytes()).hexdigest()
        actual_hash = next((line.split(" ", 1)[1] for line in output.splitlines()
                            if line.startswith("API_AUTH_FILE_SHA256 ")), None)
        print("API_AUTH_SOURCE_MATCHES_CURRENT_MAIN", actual_hash == repo_hash if actual_hash else "unknown")
    finally:
        client.close()

if __name__ == "__main__":
    main()
