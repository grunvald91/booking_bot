"""Read-only production Mail-PWA rollout preflight. Never modifies server files or flags."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from scripts.deploy_mail_search import connect

ROOT = "/opt/booking_bot"
BASE = "c80674e8ea49b4c6a4e5630967a206bad96477b5"
FILES = (
    "web/api/routes/mail_company_search.py",
    "web/api/routes/mail_campaign_dispatch.py",
    "web/api/routes/mail_campaign_review.py",
    "web/api/routes/mail_pwa.py",
    "web/api/routes/mail_campaign_dashboard.html",
    "web/api/routes/owner_mail_ui.html",
    "web/api/routes/servgo-mail-air.css",
)


def digest(b):
    return hashlib.sha256(b).hexdigest()[:16] if b is not None else "absent"


def read_file(sftp, path):
    try:
        with sftp.open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def baseline(repo: Path, path: str) -> bytes:
    result = subprocess.run(["git", "show", BASE + ":" + path], cwd=repo,
                            capture_output=True, check=True)
    return result.stdout


def command(client, value, timeout=15):
    _, output, _ = client.exec_command(value, timeout=timeout)
    content = output.read().decode("utf-8", "replace").strip()
    status = output.channel.recv_exit_status()
    return content if status == 0 else ""


def main():
    repo = Path(__file__).resolve().parents[1]
    client = connect()
    sftp = client.open_sftp()
    try:
        unit = command(client, "systemctl is-active booking-web-api.service")
        health = command(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 7 http://127.0.0.1:8000/health")
        pid = command(client, "systemctl show -p MainPID --value booking-web-api.service")
        gateway_status = command(client, "curl -sS -o /dev/null -w '%{http_code}' --max-time 9 --resolve servgo.ru:443:127.0.0.1 https://servgo.ru/api/owner-mail/workspace")
        flag = "unavailable"
        has_ai = False
        if pid.isdigit() and int(pid) > 1:
            raw = command(client, "python3 -c 'from pathlib import Path; p=Path(\"/proc/" + pid + "/environ\"); b=p.read_bytes(); print(int(b\"CLAUDEHUB_API_KEY=\" in b or b\"XAI_API_KEY=\" in b), int(b\"SERVGO_MAIL_GATEWAY_ENABLED=true\" in b or b\"SERVGO_MAIL_GATEWAY_ENABLED=1\" in b))'")
            parts = raw.split()
            if len(parts) == 2 and all(z in ("0", "1") for z in parts):
                has_ai = parts[0] == "1"
                flag = "on" if parts[1] == "1" else "off"
        print("MAIL_PREFLIGHT health=" + health + " service=" + unit +
              " gateway_url_status=" + gateway_status + " mail_flag=" + flag +
              " claudehub_key_present=" + str(has_ai).lower(), flush=True)
        conflicts = []
        needed = []
        for path in FILES:
            old = baseline(repo, path)
            new = (repo / path).read_bytes()
            current = read_file(sftp, ROOT + "/" + path)
            state = "already" if current == new else "update" if current == old else "conflict"
            if state == "conflict":
                conflicts.append(path)
            elif state == "update":
                needed.append(path)
            print("MAIL_FILE " + path + " state=" + state +
                  " server_hash=" + digest(current) + " baseline_hash=" + digest(old) +
                  " proposed_hash=" + digest(new), flush=True)
        studio_actual = read_file(sftp, ROOT + "/web/api/routes/studio_sso.py")
        studio_wanted = (repo / "web/api/routes/studio_sso.py").read_bytes()
        print("MAIL_FRONTEND_DEPENDENCY studio_sso_synced=" + str(studio_actual == studio_wanted).lower(),flush=True)
        print("MAIL_PREFLIGHT_RESULT safe_to_update=" + str(unit == "active" and health == "200" and not conflicts).lower() +
              " divergent_files=" + str(len(conflicts)) + " pending_updates=" + str(len(needed)) +
              " production_untouched=true",flush=True)
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
