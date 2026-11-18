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


# Read-only OAuth and login capability probe; never follow an OAuth login or print codes.
from urllib.parse import parse_qs, urlparse
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
def local_probe(path):
    url = "http://127.0.0.1:8000" + path
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({})).open(request, timeout=6) as resp:
            return resp.status, resp.headers, resp.read(4096)
    except urllib.error.HTTPError as ex:
        return ex.code, ex.headers, ex.read(4096)
    except Exception as ex:
        print("LOCAL_PROBE_FAILED", path, type(ex).__name__)
        return 0, {}, b""

print("YANDEX_ENV", "id=" + ("present" if api.get("YANDEX_CLIENT_ID") else "missing"),
      "secret=" + ("present" if api.get("YANDEX_CLIENT_SECRET") else "missing"),
      "jwt=" + ("long" if len(api.get("JWT_SECRET", "")) >= 32 else "short_or_missing"))
status, headers, body = local_probe("/auth/yandex/capabilities")
try:
    available = json.loads(body).get("available")
except Exception:
    available = "unknown"
print("YANDEX_CAPABILITIES", "http=" + str(status), "available=" + str(available))
status, headers, body = local_probe("/auth/yandex/start")
url = urlparse(headers.get("Location", ""))
params = parse_qs(url.query)
print("YANDEX_START", "http=" + str(status), "oauth_host_ok=" + str(url.netloc == "oauth.yandex.ru"),
      "client_id_present=" + str(bool(params.get("client_id"))),
      "callback_ok=" + str(params.get("redirect_uri") == ["https://servgo.ru/api/auth/yandex/callback"]),
      "pkce_ok=" + str(params.get("code_challenge_method") == ["S256"]),
      "cookie=" + str("servgo_yx" in headers.get("set-cookie", "")))
# Public OAuth page must accept the registered client/redirect; this never signs in.
if status == 302 and url.netloc == "oauth.yandex.ru":
    try:
        target = headers.get("Location", "")
        req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({})).open(req, timeout=10) as response:
            upstream_status = response.status
            response_type = response.headers.get("content-type", "").split(";")[0]
            print("YANDEX_OAUTH_AUTHORIZATION_PAGE", "http=" + str(upstream_status), "content_type=" + response_type)
    except urllib.error.HTTPError as ex:
        print("YANDEX_OAUTH_AUTHORIZATION_PAGE", "http=" + str(ex.code))
    except Exception as ex:
        print("YANDEX_OAUTH_AUTHORIZATION_PAGE", "unavailable_" + type(ex).__name__)

# Non-personal login widget iframe diagnostic; inspect only provider error markers.
try:
    import urllib.parse
    tg_url = "https://tg.servgo.ru/embed/sochi_servgo_bot?origin=" + urllib.parse.quote("https://servgo.ru", safe="") + "&size=large"
    req = urllib.request.Request(tg_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({})).open(req, timeout=9) as response:
        snippet = response.read(120000).decode("utf-8", "replace").lower()
        print("TELEGRAM_WIDGET_IFRAME", "http=" + str(response.status),
              "bot_domain_invalid_marker=" + str("bot domain invalid" in snippet),
              "contains_authorization_ui=" + str("telegram" in snippet))
except urllib.error.HTTPError as ex:
    print("TELEGRAM_WIDGET_IFRAME", "http=" + str(ex.code))
except Exception as ex:
    print("TELEGRAM_WIDGET_IFRAME", "unavailable_" + type(ex).__name__)


try:
    old_url = "https://tg.servgo.ru/embed/Sochiservice_bot?origin=" + urllib.parse.quote("https://servgo.ru", safe="") + "&size=large"
    req = urllib.request.Request(old_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({})).open(req, timeout=9) as response:
        old_snippet = response.read(120000).decode("utf-8", "replace").lower()
        print("LEGACY_TELEGRAM_WIDGET_IFRAME", "http=" + str(response.status),
              "bot_domain_invalid_marker=" + str("bot domain invalid" in old_snippet))
except Exception as exc:
    print("LEGACY_TELEGRAM_WIDGET_IFRAME", "unavailable_" + type(exc).__name__)

# Search only known application-managed configuration locations; never output or store secrets.
import glob
candidates = set(glob.glob("/opt/booking_bot/.env*") + glob.glob("/etc/servgo/*bot*.env") +
                 glob.glob("/etc/servgo/*telegram*.env"))
available_bots = set()
for filename in sorted(candidates)[:35]:
    try:
        f = Path(filename)
        if not f.is_file() or f.stat().st_size > 100000:
            continue
        for line in f.read_text(errors="replace").splitlines():
            entry = line.strip()
            if entry.startswith("export "):
                entry = entry[7:]
            if not entry.startswith(("BOT_TOKEN=", "TELEGRAM_LOGIN_BOT_TOKEN=")):
                continue
            candidate = entry.split("=", 1)[1].strip().strip("'").strip('"')
            if not candidate:
                continue
            # Only Telegram API sees the supplied token in HTTPS; exceptions never print URLs.
            url = "https://api.telegram.org/bot" + candidate + "/getMe"
            req = urllib.request.Request(url)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as resp:
                doc = json.load(resp)
            who = (doc.get("result") or {}).get("username", "").lower()
            if who in ("sochiservice_bot", "sochi_servgo_bot"):
                available_bots.add(who)
    except Exception:
        pass
print("AVAILABLE_LEGACY_LOGIN_BOT_TOKEN", "sochiservice_bot" in available_bots)

status, headers, body = local_probe("/auth/yandex/callback?state=invalid")
print("YANDEX_INVALID_CALLBACK", "http=" + str(status),
      "safe_redirect=" + str(headers.get("Location", "").startswith("/login?yandex=")))

for label, path in (("EMAIL", "/auth/email/capabilities"), ("VK", "/auth/vk/capabilities")):
    status, headers, body = local_probe(path)
    print(label + "_CAPABILITIES", "http=" + str(status))
rc, logs = run(["journalctl", "-u", "booking-web-api.service", "--since", "-12 hours", "-n", "2500", "--no-pager", "-o", "cat"])
if rc == 0:
    lines = logs.splitlines()
    for marker in ("yandex_login_failed:", "yandex_code_send_failed:", "Invalid Telegram auth payload",
                   "yandex", "/auth/yandex/callback"):
        print("AUTH_LOG_COUNT", marker.replace(" ", "_"), sum(marker.lower() in line.lower() for line in lines))
else:
    print("AUTH_LOG_COUNTS_UNAVAILABLE")

# This is aggregate only; it cannot identify the owner of a specific Telegram or Yandex account.
# No user, business, phone, login, e-mail or token data is returned.
db_code = """
import asyncio
from sqlalchemy import select, func
from database.models import User, YandexIdentity, EmailIdentity, Business, BusinessOwner, UserAccountMerge
from database.database import engine
async def main():
    async with engine.connect() as db:
        for name, statement in (
            ("yandex_total", select(func.count()).select_from(YandexIdentity)),
            ("yandex_on_telegram_user", select(func.count()).select_from(YandexIdentity).join(User, YandexIdentity.user_id == User.id).where(User.telegram_id > 0)),
            ("yandex_on_business_owner", select(func.count(func.distinct(YandexIdentity.user_id))).select_from(YandexIdentity).join(Business, Business.owner_id == YandexIdentity.user_id)),
            ("yandex_on_business_coowner", select(func.count(func.distinct(YandexIdentity.user_id))).select_from(YandexIdentity).join(BusinessOwner, BusinessOwner.user_id == YandexIdentity.user_id)),
            ("yandex_and_email_on_same_user", select(func.count()).select_from(YandexIdentity).join(EmailIdentity, EmailIdentity.user_id == YandexIdentity.user_id)),
            ("yandex_telegram_owner_named_artur", select(func.count()).select_from(YandexIdentity).join(User, User.id == YandexIdentity.user_id).join(Business, Business.owner_id == User.id).where(User.telegram_id > 0, User.full_name.ilike("%артур%"))),
            ("email_total", select(func.count()).select_from(EmailIdentity)),
            ("merged_accounts_total", select(func.count()).select_from(UserAccountMerge)),
        ):
            print("AUTH_DB_AGG", name, (await db.execute(statement)).scalar_one())
    await engine.dispose()
asyncio.run(main())
"""
try:
    proc = subprocess.run(["/opt/booking_bot/venv/bin/python", "-c", db_code],
        cwd="/opt/booking_bot", env={**os.environ, **api}, capture_output=True, text=True, timeout=15)
    if proc.returncode == 0:
        print(proc.stdout)
    else:
        print("AUTH_DB_AGG", "unavailable", "exit_code=" + str(proc.returncode))
except Exception as exc:
    print("AUTH_DB_AGG", "unavailable_" + type(exc).__name__)


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
