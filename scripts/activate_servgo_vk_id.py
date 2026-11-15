"""Guarded one-time activation of the PUBLIC VK ID App ID for ServGo.

On the PR branch: READ ONLY production verification.
On reviewed main: update ONLY the isolated systemd drop-in, with rollback.
No changes to account tables, tokens, the OAuth handler, or any other auth path.
"""
from __future__ import annotations

import json
import os
import shlex
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.deploy_business_creation_and_reminders import (
    WEB_SERVICE, ROOT, connect, run, wait_web_ready,
)

APP_ID = "54898639"  # Public client identifier, not a secret.
CALLBACK = "https://servgo.ru/api/auth/vk/callback"
DROP_IN_DIR = "/etc/systemd/system/booking-web-api.service.d"
DROP_IN = DROP_IN_DIR + "/90-servgo-vk-id.conf"
CONTENT = (
    "[Service]\n"
    'Environment="SERVGO_VK_ID_APP_ID=' + APP_ID + '"\n'
    'Environment="SERVGO_VK_ID_REDIRECT_URI=' + CALLBACK + '"\n'
).encode("ascii")


def remote_python(client, source: str, timeout: int = 65) -> str:
    """Execute isolated read-only probe with effective API process env.

    Only explicit, non-sensitive statuses are returned to runner logs.
    """
    bootstrap = """
import os, pathlib, subprocess
pid = subprocess.check_output(
  ['systemctl', 'show', '-p', 'MainPID', '--value', 'booking-web-api.service'],
  text=True).strip()
if not pid.isdigit() or int(pid) < 2:
    raise RuntimeError('Invalid API PID')
pairs = pathlib.Path('/proc/' + pid + '/environ').read_bytes().split(bytes([0]))
for pair in pairs:
    if b'=' in pair:
        key, _, value = pair.partition(b'=')
        os.environ[key.decode('utf-8')] = value.decode('utf-8')
"""
    return run(
        client,
        "cd " + shlex.quote(ROOT) + " && ./venv/bin/python -c " +
        shlex.quote(bootstrap + "\n" + source),
        timeout,
    )


def probe(client) -> dict:
    body = remote_python(client, """
import json, asyncio
from sqlalchemy import text
from web.api.database import engine
from web.api.routes import vk_auth
from web.api import deps

async def db_tables():
    async with engine.connect() as conn:
        result = {}
        for name in ("vk_identities", "vk_login_tickets"):
            row = await conn.execute(text("SELECT to_regclass(:n)"), {"n": name})
            result[name] = row.scalar() is not None
    await engine.dispose()
    return result

current = os.getenv("SERVGO_VK_ID_APP_ID", "").strip()
print(json.dumps({
    "app_id_absent_or_expected": current in ("", "54898639"),
    "app_id_already_expected": current == "54898639",
    "redirect_compatible": os.getenv("SERVGO_VK_ID_REDIRECT_URI", "https://servgo.ru/api/auth/vk/callback") == "https://servgo.ru/api/auth/vk/callback",
    "session_secret_ready": len(deps.SECRET_KEY) >= 32,
    "route_ready": hasattr(vk_auth, "configured"),
    "db_tables": asyncio.run(db_tables()),
}, sort_keys=True))
""", 80)
    try:
        data = json.loads(body.splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("Could not parse safe VK preflight") from None
    return data


def api_check(client, expected: bool) -> None:
    """No real OAuth account, only loopback availability and redirect contract."""
    script = """
import json
import httpx
from urllib.parse import parse_qs, urlparse
with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
    ready = client.get('http://127.0.0.1:8000/health')
    vk = client.get('http://127.0.0.1:8000/auth/vk/capabilities')
    yandex = client.get('http://127.0.0.1:8000/auth/yandex/capabilities')
    assert ready.status_code == 200, 'Health failure'
    assert vk.status_code == 200 and isinstance(vk.json().get('available'), bool), 'VK capabilities failure'
    assert yandex.status_code == 200, 'Yandex auth regression'
    assert vk.json()['available'] is %r, 'VK capability not as expected'
    if %r:
        first = client.get('http://127.0.0.1:8000/auth/vk/start')
        uri = urlparse(first.headers.get('location',''))
        q = parse_qs(uri.query)
        assert first.status_code == 302 and uri.netloc == 'id.vk.ru', 'VK start failure'
        assert q.get('client_id') == ['54898639'], 'Wrong VK App ID'
        assert q.get('redirect_uri') == ['https://servgo.ru/api/auth/vk/callback'], 'Wrong callback'
        assert q.get('code_challenge_method') == ['s256'], 'PKCE not active'
        assert 'servgo_vk_flow' in first.headers.get('set-cookie',''), 'State cookie absent'
    print('API_HEALTH=200 YANDEX=200 VK_READY=' + str(vk.json()['available']).lower())
""" % (expected, expected)
    print(remote_python(client, script, 45))


def sftp_read(sftp, path: str) -> bytes | None:
    try:
        with sftp.open(path, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def main() -> None:
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("GitHub SERVER_SSH_PASSWORD unavailable")
    apply = os.environ.get("APPLY", "false").lower() == "true"
    client = connect(password)  # Pinned production SSH host key.
    sftp = client.open_sftp()
    changed = False
    previous = None
    try:
        if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
            raise RuntimeError("Production booking API inactive")
        current = probe(client)
        print("VK_PRECHECK=" + json.dumps(current, sort_keys=True))
        if not (
            current.get("app_id_absent_or_expected")
            and current.get("redirect_compatible")
            and current.get("session_secret_ready")
            and current.get("route_ready")
            and current.get("db_tables", {}).get("vk_identities")
            and current.get("db_tables", {}).get("vk_login_tickets")
        ):
            raise RuntimeError("Missing DB schema, route, secret, or incompatible VK configuration")
        # Avoid touching anything until we confirm the deployed route exactly
        # matches reviewed source; older or modified auth logic must not be enabled.
        live_route = sftp_read(sftp, ROOT + "/web/api/routes/vk_auth.py")
        reviewed = (Path(__file__).resolve().parents[1] / "web/api/routes/vk_auth.py").read_bytes()
        if live_route != reviewed:
            raise RuntimeError("Live VK OAuth route differs from reviewed main; activation refused")

        previous = sftp_read(sftp, DROP_IN)
        if previous not in (None, CONTENT):
            raise RuntimeError("Existing VK systemd drop-in differs; refusing overwrite")
        if not apply:
            api_check(client, bool(current["app_id_already_expected"]))
            print("VK_ACTIVATION_PREFLIGHT=passed mutation=false proposed_app_id=" + APP_ID)
            return

        if previous == CONTENT and current["app_id_already_expected"]:
            api_check(client, True)
            print("VK_ACTIVATION=already_active")
            return

        run(client, "install -d -m 0755 " + shlex.quote(DROP_IN_DIR))
        # Safe atomic file install, without modifying main service or shared .env.
        stage = DROP_IN + ".stage-" + str(int(time.time()))
        try:
            with sftp.open(stage, "wb") as stream:
                stream.write(CONTENT)
            sftp.chmod(stage, 0o644)
            sftp.posix_rename(stage, DROP_IN)
            changed = True
        finally:
            if sftp_read(sftp, stage) is not None:
                sftp.remove(stage)
        run(client, "systemctl daemon-reload && systemctl restart " + WEB_SERVICE, 90)
        wait_web_ready(client)
        after = probe(client)
        if not after["app_id_already_expected"]:
            raise RuntimeError("Effective service process did not inherit App ID")
        api_check(client, True)
        print("VK_ACTIVATION=success app_id=" + APP_ID + " original_auth_paths_unchanged=true")
    except Exception:
        if changed:
            try:
                if previous is None:
                    sftp.remove(DROP_IN)
                else:
                    with sftp.open(DROP_IN, "wb") as restored:
                        restored.write(previous)
                    sftp.chmod(DROP_IN, 0o644)
                run(client, "systemctl daemon-reload && systemctl restart " + WEB_SERVICE, 90)
                wait_web_ready(client)
                api_check(client, False)
                print("VK_ACTIVATION_ROLLBACK=passed")
            except Exception:
                print("VK_ACTIVATION_ROLLBACK=failed needs_manual_review")
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
