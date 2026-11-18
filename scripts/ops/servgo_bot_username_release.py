"""Guarded one-shot fix: align only the ServGo login bot name with its existing token.

Scope: /opt/booking_bot/.env BOT_USERNAME, booking-web-api.service only.
No token changes, no database writes, no other service restarts.
Pinned SSH host, strict old-value guard, protected backup, atomic write, rollback.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import shlex
import time

from scripts.deploy_business_creation_and_reminders import connect, run, wait_web_ready, ROOT, WEB_SERVICE

CONFIG = ROOT + "/.env"
NEW_BOT = "sochi_servgo_bot"
OLD_BOT = "sochiservice_bot"

VALIDATE_TOKEN = """
import json
from pathlib import Path
import urllib.request
value = None
for line in Path('/opt/booking_bot/.env').read_text(errors='replace').splitlines():
    if line.startswith('BOT_TOKEN='):
        value = line.split('=', 1)[1].strip().strip("'").strip('"')
        break
if not value:
    raise SystemExit(1)
try:
    req = urllib.request.Request('https://api.telegram.org/bot' + value + '/getMe')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=9) as response:
        data = json.load(response)
    print('yes' if data.get('ok') and
          (data.get('result') or {}).get('username', '').lower() == 'sochi_servgo_bot' else 'no')
except Exception:
    print('no')
"""

CHECK_ENV = """
import pathlib, subprocess
pid = subprocess.check_output(['systemctl', 'show', 'booking-web-api.service',
                               '--property=MainPID', '--value'], text=True).strip()
env = pathlib.Path('/proc/' + pid + '/environ').read_bytes()
values = dict(item.split(b'=', 1) for item in env.split(b'\\0') if b'=' in item)
print('yes' if values.get(b'BOT_USERNAME', b'').lower() == b'sochi_servgo_bot' else 'no')
"""


def rewrite_username(original: bytes) -> tuple[bytes, bool]:
    """Only replace the one reviewed BOT_USERNAME value, preserving everything else."""
    lines = original.decode("utf-8").splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if line.startswith("BOT_USERNAME=")]
    if len(indices) != 1:
        raise RuntimeError("Expected exactly one BOT_USERNAME entry; refusing to change .env")
    index = indices[0]
    match = re.fullmatch(r"""(BOT_USERNAME=)(['"]?)([A-Za-z0-9_]{5,32})\2([ \t]*\r?\n?)""", lines[index])
    if match is None:
        raise RuntimeError("Unsupported BOT_USERNAME syntax; refusing to change .env")
    prefix, quote, name, end = match.groups()
    if name.lower() == NEW_BOT:
        return original, False
    if name.lower() != OLD_BOT:
        raise RuntimeError("Unexpected configured bot username; refusing to overwrite it")
    lines[index] = prefix + quote + NEW_BOT + quote + end
    return "".join(lines).encode("utf-8"), True


def server_python(client, source: str) -> str:
    encoded = base64.b64encode(source.encode()).decode()
    return run(client, "python3 -c " + shlex.quote(
        "import base64;exec(base64.b64decode(" + repr(encoded) + "))"), 25).strip()


def verify_running(client) -> None:
    if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
        raise RuntimeError("ServGo API is inactive")
    wait_web_ready(client)
    if server_python(client, CHECK_ENV) != "yes":
        raise RuntimeError("Active API does not have expected BOT_USERNAME")


def main() -> None:
    password = os.getenv("SERVER_SSH_PASSWORD", "")
    if not password:
        raise RuntimeError("Missing production SSH secret")
    apply = os.getenv("APPLY", "false").lower() == "true"
    client = connect(password)
    backup = ""
    updated = False
    sftp = None
    try:
        sftp = client.open_sftp()
        if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
            raise RuntimeError("ServGo API inactive; refusing update")
        with sftp.open(CONFIG, "rb") as handle:
            original = handle.read()
        desired, changed = rewrite_username(original)
        original_sha = hashlib.sha256(original).hexdigest()
        print("username_config_action=" + ("update" if changed else "already"))
        if server_python(client, VALIDATE_TOKEN) != "yes":
            raise RuntimeError("Existing BOT_TOKEN does not match the approved login bot")
        if not apply:
            print("preflight_ok=true production_untouched=true")
            return
        if not changed:
            verify_running(client)
            print("username_release_ok=true already_applied=true")
            return
        mode = sftp.stat(CONFIG).st_mode & 0o777
        backup = CONFIG + ".bak.bot-username." + str(int(time.time()))
        run(client, "cp -p " + shlex.quote(CONFIG) + " " + shlex.quote(backup))
        temp = CONFIG + ".new.bot-username"
        with sftp.open(temp, "wb") as out:
            out.write(desired)
        sftp.chmod(temp, mode)
        # Block concurrent edits even after the initial preflight.
        with sftp.open(CONFIG, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() != original_sha:
                raise RuntimeError("Source changed during rollout; refusing rename")
        updated = True
        sftp.posix_rename(temp, CONFIG)
        run(client, "systemctl restart " + WEB_SERVICE, 65)
        verify_running(client)
        print("username_release_ok=true changed_files=1 api_health=200 rollback_backup_saved=true")
    except Exception:
        if updated and backup:
            try:
                run(client, "cp -p " + shlex.quote(backup) + " " + shlex.quote(CONFIG))
                run(client, "systemctl restart " + WEB_SERVICE, 65)
                wait_web_ready(client)
                print("username_rollback_ok=true")
            except Exception:
                print("username_rollback_incomplete=true")
        raise
    finally:
        if sftp is not None:
            sftp.close()
        client.close()


if __name__ == "__main__":
    main()
