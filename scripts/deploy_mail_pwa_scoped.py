"""Guarded production Mail-only release after a clean preflight.

No frontend assets, no studio_sso changes, no gateway flag changes, no email send.
Rollback restores every touched file and the API service if a check fails.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import time

from scripts.deploy_mail_search import connect, put, run
from scripts.mail_pwa_server_preflight import BASE, FILES, ROOT, baseline, read_file

SERVICE = "booking-web-api.service"
BACKUP_DIR = ROOT + "/.servgo-mail-pwa-backups"


def sha(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else "absent"


def http(client, site: str, path: str = "/") -> str:
    url = "https://" + site + path
    cmd = ("curl -sS --max-time 12 --resolve " + shlex.quote(site + ":443:127.0.0.1")
           + " -o /dev/null -w '%{http_code}' " + shlex.quote(url))
    return run(client, cmd)


def health(client):
    status = run(client, "curl -sS --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health")
    if status != "200":
        raise RuntimeError("API health is not 200")


def main():
    apply = os.environ.get("APPLY", "false").lower() == "true"
    repo = Path(__file__).resolve().parents[1]
    # All source paths must already compile before touching SSH.
    desired = {p: (repo / p).read_bytes() for p in FILES}
    old = {p: baseline(repo, p) for p in FILES}
    for path, data in desired.items():
        if path.endswith(".py"):
            compile(data, path, "exec")
    client = connect()
    sftp = client.open_sftp()
    changed = []
    backup_root = BACKUP_DIR + "/" + str(int(time.time()))
    prior = {}
    needs_restart = False
    try:
        if run(client, "systemctl is-active " + SERVICE) != "active":
            raise RuntimeError("Mail API service not active")
        health(client)
        gateway_before = http(client, "servgo.ru", "/api/owner-mail/workspace")
        if gateway_before != "303":
            raise RuntimeError("Canonical Mail HTTPS entry is not enabled/returning 303")
        legacy_before = http(client, "mail.servgo.ru")
        if legacy_before not in ("200", "301", "302", "303", "401", "403"):
            raise RuntimeError("Legacy mail domain not available")
        todo = []
        for path in FILES:
            actual = read_file(sftp, ROOT + "/" + path)
            if actual == desired[path]:
                state = "already"
            elif actual == old[path]:
                state = "update"
                todo.append(path)
            else:
                state = "conflict"
            print("MAIL_RELEASE_FILE " + path + " state=" + state, flush=True)
            if state == "conflict":
                raise RuntimeError("Mail production file diverged; refusing deploy: " + path)
            prior[path] = actual
        print("MAIL_RELEASE_PREFLIGHT success=true pending_files=" + str(len(todo)) +
              " legacy_http=" + legacy_before + " gateway_http=" + gateway_before, flush=True)
        if not apply:
            print("MAIL_RELEASE_DRY_RUN production_untouched=true", flush=True)
            return
        if not todo:
            print("MAIL_RELEASE_RESULT already_deployed=true", flush=True)
            return
        # Backup EVERY file before changing ANY file.
        run(client, "install -d -m 0700 " + shlex.quote(BACKUP_DIR) +
            " && install -d -m 0700 " + shlex.quote(backup_root))
        for path in todo:
            backup = backup_root + "/" + path
            target = ROOT + "/" + path
            run(client, "install -d -m 0700 " + shlex.quote(str(Path(backup).parent)) +
                " && cp -p " + shlex.quote(target) + " " + shlex.quote(backup))
        for path in todo:
            target = ROOT + "/" + path
            mode = sftp.stat(target).st_mode & 0o777
            changed.append(path)
            put(sftp, target, desired[path], mode)
            if sha(read_file(sftp, target)) != sha(desired[path]):
                raise RuntimeError("Mail file checksum changed in transit: " + path)
        python_paths = [p for p in todo if p.endswith(".py")]
        if python_paths:
            run(client, "cd " + shlex.quote(ROOT) + " && ./venv/bin/python -m py_compile " +
                " ".join(shlex.quote(x) for x in python_paths))
        needs_restart = True
        run(client, "systemctl restart " + SERVICE, timeout=65)
        for _ in range(20):
            try:
                health(client)
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError("Mail API failed health after restart")
        if http(client, "servgo.ru", "/api/owner-mail/workspace") != gateway_before:
            raise RuntimeError("Canonical Mail workspace redirect changed unexpectedly")
        if http(client, "mail.servgo.ru") != legacy_before:
            raise RuntimeError("Legacy Mail domain changed HTTP status")
        if http(client, "servgo.ru", "/api/owner-mail/api/company-search") not in ("401", "403"):
            raise RuntimeError("Mail search API does not require owner authentication")
        print("MAIL_RELEASE_RESULT deployed=true changed_files=" + str(len(changed)) +
              " health=200 gateway_http=303 legacy_http=" + legacy_before +
              " database_changed=false email_sent_by_release=false "+
              " frontend_changed=false worker_not_restarted=true", flush=True)
    except Exception:
        if changed:
            try:
                for path in reversed(changed):
                    target = ROOT + "/" + path
                    backup = backup_root + "/" + path
                    run(client, "cp -p " + shlex.quote(backup) + " " + shlex.quote(target))
                run(client, "systemctl restart " + SERVICE, timeout=65)
                for _ in range(20):
                    try:
                        health(client)
                        break
                    except Exception:
                        time.sleep(2)
                print("MAIL_RELEASE_ROLLBACK restored=true", flush=True)
            except Exception:
                print("MAIL_RELEASE_ROLLBACK restored=false; manual intervention required", flush=True)
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
