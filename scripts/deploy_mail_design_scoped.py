"""Guarded, scoped ServGo Mail design/UI release from the reviewed main merge.

Only two Mail HTML pages, their stylesheet, and two backend routes are staged.
No changes to SMTP, mail workers, database, nginx, Studio, JS bundle, or users.
Refuse any production file that no longer matches the pre-PR main baseline.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import time

from scripts.deploy_mail_search import connect, put, run

ROOT = "/opt/booking_bot"
SERVICE = "booking-web-api.service"
BASE_SHA = "2956d1fbd08488fe653b92c519948fae386daae4"
FILES = (
    "web/api/routes/mail_campaign_dashboard.html",
    "web/api/routes/owner_mail_ui.html",
    "web/api/routes/servgo-mail-air.css",
    "web/api/routes/mail_campaign_ui.py",
    "web/api/routes/mail_pwa.py",
)
BACKUP_ROOT = ROOT + "/.servgo-mail-design-backups"


def sha(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else "absent"


def baseline(repo: Path, path: str) -> bytes:
    return subprocess.run(["git", "show", BASE_SHA + ":" + path],
                          cwd=repo, capture_output=True, check=True).stdout


def read(sftp, path: str) -> bytes | None:
    try:
        with sftp.open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def code(client, domain: str, path: str = "/") -> str:
    cmd = ("curl -sS --max-time 12 --resolve "
           + shlex.quote(domain + ":443:127.0.0.1")
           + " -o /dev/null -w '%{http_code}' "
           + shlex.quote("https://" + domain + path))
    return run(client, cmd)


def healthy(client):
    result = run(client, "curl -sS --max-time 9 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health")
    if result != "200":
        raise RuntimeError("BookingBot API health check failed")


def verify(client):
    healthy(client)
    routes = (
        ("servgo.ru", "/workspace/mail", {"200"}),
        ("servgo.ru", "/api/owner-mail/workspace", {"303"}),
        ("servgo.ru", "/api/owner-mail/api/company-search", {"401", "403"}),
        ("mail.servgo.ru", "/", {"200"}),
        ("servgo.ru", "/api/owner-mail/api/servgo-mail-air.css?v=3", {"200"}),
        ("mail.servgo.ru", "/api/servgo-mail-air.css?v=3", {"200"}),
        ("servgo.ru", "/api/owner-mail/api/servgo-air-onest-cyrillic.woff2", {"200"}),
        ("servgo.ru", "/api/owner-mail/api/servgo-air-onest-latin.woff2", {"200"}),
        ("mail.servgo.ru", "/api/servgo-air-onest-cyrillic.woff2", {"200"}),
    )
    for domain, path, expected in routes:
        response = code(client, domain, path)
        if response not in expected:
            raise RuntimeError("Mail route verification failed: "+domain+path+" HTTP "+response)
        print("MAIL_DESIGN_HTTP "+domain+path+"="+response, flush=True)
    print("MAIL_DESIGN_VERIFY api_health=200 origin_checks_passed=true", flush=True)


def main():
    repo = Path(__file__).resolve().parents[1]
    apply = os.environ.get("APPLY", "false").casefold() == "true"
    desired = {name: (repo / name).read_bytes() for name in FILES}
    before = {name: baseline(repo, name) for name in FILES}
    for name in FILES:
        if name.endswith(".py"):
            compile(desired[name], name, "exec")

    client = connect()
    sftp = client.open_sftp()
    changed: list[str] = []
    stamp = str(int(time.time()))
    backup_dir = BACKUP_ROOT + "/" + stamp
    try:
        if run(client, "systemctl is-active " + SERVICE) != "active":
            raise RuntimeError("BookingBot web API inactive")
        healthy(client)
        if code(client, "servgo.ru", "/api/owner-mail/workspace") != "303":
            raise RuntimeError("Canonical mail entry unavailable")
        if code(client, "mail.servgo.ru", "/") != "200":
            raise RuntimeError("Legacy Mail unavailable")
        # The frontend owns both cyrillic & latin fonts already.
        for subset in ("cyrillic", "latin"):
            cmd = ("find "+shlex.quote(ROOT+"/web/frontend/dist/assets")
                   +" -maxdepth 1 -type f -name "
                   +shlex.quote("onest-"+subset+"-wght-normal-*.woff2")
                   +" -print -quit | grep -q . && echo present")
            if run(client, cmd) != "present":
                raise RuntimeError("Required local Onest asset missing: "+subset)
        todo: list[str] = []
        for path in FILES:
            live = read(sftp, ROOT + "/" + path)
            status = "already" if live == desired[path] else "update" if live == before[path] else "conflict"
            print("MAIL_DESIGN_FILE path="+path+" status="+status,flush=True)
            if status == "conflict":
                raise RuntimeError("Production Mail file diverged: "+path)
            if status == "update":
                todo.append(path)
        print("MAIL_DESIGN_PREFLIGHT passed=true pending="+str(len(todo))+
              " apply="+str(apply).lower(),flush=True)
        if not apply:
            print("MAIL_DESIGN_DRYRUN production_untouched=true",flush=True)
            return
        if not todo:
            verify(client)
            print("MAIL_DESIGN_RELEASE already_deployed=true",flush=True)
            return
        run(client,"install -d -m 0700 "+shlex.quote(BACKUP_ROOT)+
            " && install -d -m 0700 "+shlex.quote(backup_dir))
        # Back up all targets BEFORE the first write, with their original modes.
        for path in todo:
            dest = backup_dir+"/"+path
            run(client,"install -d -m 0700 "+shlex.quote(str(Path(dest).parent))+
                " && cp -p "+shlex.quote(ROOT+"/"+path)+" "+shlex.quote(dest))
        for path in todo:
            target = ROOT+"/"+path
            mode = sftp.stat(target).st_mode & 0o777
            changed.append(path)
            put(sftp,target,desired[path],mode)
            if sha(read(sftp,target)) != sha(desired[path]):
                raise RuntimeError("Deployed Mail file checksum mismatch: "+path)
        py = [path for path in todo if path.endswith(".py")]
        if py:
            run(client,"cd "+shlex.quote(ROOT)+" && ./venv/bin/python -m py_compile "+
                " ".join(shlex.quote(path) for path in py),50)
        run(client,"systemctl restart "+SERVICE,65)
        for attempt in range(18):
            try:
                healthy(client)
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError("Booking API did not restart cleanly")
        verify(client)
        print("MAIL_DESIGN_RELEASE deployed=true changed="+str(len(changed))+
              " frontend_unchanged=true worker_unchanged=true"
              " database_unchanged=true smtp_messages_sent=0",flush=True)
    except Exception:
        if changed:
            try:
                for path in reversed(changed):
                    run(client,"cp -p "+shlex.quote(backup_dir+"/"+path)+
                        " "+shlex.quote(ROOT+"/"+path))
                run(client,"systemctl restart "+SERVICE,65)
                for attempt in range(18):
                    try:
                        healthy(client)
                        break
                    except Exception:
                        time.sleep(2)
                print("MAIL_DESIGN_ROLLBACK restored=true",flush=True)
            except Exception:
                print("MAIL_DESIGN_ROLLBACK restored=failed_manual_action_needed",flush=True)
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
