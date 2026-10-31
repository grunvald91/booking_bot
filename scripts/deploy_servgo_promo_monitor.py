"""Guarded split of promo.servgo.ru from booking Telegram polling.

Runs through pinned SSH. With APPLY=false, changes NOTHING on production.
Only new code/units and the promo-only nginx vhost may be changed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
ROOT = "/opt/booking_bot"
SITE = "/etc/nginx/sites-enabled/servgo-promo"
PORT = 18080
UNIT = "servgo-promo-web.service"
TIMER = "servgo-health-monitor.timer"
FILES = {
    "webapp/promo_standalone.py": ROOT + "/webapp/promo_standalone.py",
    "ops/servgo_monitor.py": ROOT + "/ops/servgo_monitor.py",
    "deploy/systemd/servgo-promo-web.service": "/etc/systemd/system/servgo-promo-web.service",
    "deploy/systemd/servgo-health-monitor.service": "/etc/systemd/system/servgo-health-monitor.service",
    "deploy/systemd/servgo-health-monitor.timer": "/etc/systemd/system/servgo-health-monitor.timer",
}


def nginx_promo_transform(old: str) -> str:
    """Never touch another vhost. Both promo / and /static/ go to the new port."""
    names = re.findall(r"\bserver_name\s+([^;]+);", old)
    if len(names) != 2 or any(x.strip() != "promo.servgo.ru" for x in names):
        raise ValueError("Expected one isolated promo vhost file with two promo server blocks")
    previous = "proxy_pass http://127.0.0.1:8080/"
    upgraded = f"proxy_pass http://127.0.0.1:{PORT}/"
    if old.count(upgraded) == 2 and old.count(previous) == 0:
        return old
    if old.count(previous) != 2 or old.count(upgraded):
        raise ValueError("Unexpected promo upstream; refusing to rewrite nginx")
    if "location /static/" not in old or "location / {" not in old:
        raise ValueError("Unrecognized promo routing layout")
    return old.replace(previous, upgraded)


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def shell(s: str) -> str:
    return shlex.quote(s)


def read_optional(sftp, path: str) -> bytes | None:
    try:
        with sftp.open(path, "rb") as stream:
            return stream.read()
    except OSError:
        return None


def put_atomic(sftp, path: str, data: bytes, mode: int = 0o644):
    temp = path + ".servgo-next"
    with sftp.open(temp, "wb") as stream:
        stream.write(data)
    sftp.chmod(temp, mode)
    sftp.posix_rename(temp, path)


def main() -> None:
    import paramiko  # noqa: F401
    from scripts.deploy_business_creation_and_reminders import connect, run

    password = os.environ.get("SERVGO_PASSWORD")
    if not password:
        raise RuntimeError("Missing SSH secret")
    apply = os.environ.get("APPLY", "false").lower() == "true"
    remote = connect(password)
    sftp = remote.open_sftp()
    written = []
    started = False
    switched = False
    site_path = SITE
    site_old = None
    try:
        if run(remote, "nginx -t >/dev/null 2>&1 && echo ok") != "ok":
            raise RuntimeError("nginx preflight failed")
        if run(remote, "systemctl is-active booking-bot.service || true") != "active":
            raise RuntimeError("Legacy promo site not healthy; refusing migration")
        if run(remote, "curl -ksS -o /dev/null -w '%{http_code}' --max-time 6 "
                        "--resolve promo.servgo.ru:443:127.0.0.1 https://promo.servgo.ru/") != "200":
            raise RuntimeError("Legacy promo health baseline is not 200")
        site_path = run(remote, "readlink -f " + shell(SITE))
        if not site_path.startswith("/etc/nginx/"):
            raise RuntimeError("Unexpected promo nginx config path")
        site_old = read_optional(sftp, site_path)
        if not site_old:
            raise RuntimeError("Promo nginx config missing")
        site_new = nginx_promo_transform(site_old.decode("utf-8")).encode("utf-8")
        # Never take over an unrecognized process already bound to our new port.
        port_state = run(remote, "ss -ltn | grep -q ':18080 ' && echo occupied || echo free")
        current_unit = run(remote, "systemctl is-active servgo-promo-web.service || true")
        if port_state == "occupied" and current_unit != "active":
            raise RuntimeError("Promo port 18080 is already occupied by another service")

        to_copy = {}
        for local, target in FILES.items():
            content = (REPO / local).read_bytes()
            old = read_optional(sftp, target)
            if old is not None and old != content:
                raise RuntimeError("Unreviewed existing production file: " + target)
            if old is None:
                to_copy[target] = content

        print(f"preflight=ok apply={apply} isolated_nginx={site_path} "
              f"new_files={len(to_copy)} site_change={site_new != site_old}", flush=True)
        if not apply:
            print("production_untouched=true", flush=True)
            return

        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup_dir = ROOT + "/releases/promo-isolation-" + stamp
        run(remote, "install -d -m 0700 " + shell(backup_dir))
        with sftp.open(backup_dir + "/servgo-promo.nginx.orig", "wb") as out:
            out.write(site_old)
        for target, content in to_copy.items():
            run(remote, "install -d -m 0755 " + shell(str(Path(target).parent)))
            put_atomic(sftp, target, content)
            written.append(target)
            if read_optional(sftp, target) != content:
                raise RuntimeError("Upload verification failed: " + target)

        run(remote, "cd " + shell(ROOT) + " && venv/bin/python -m py_compile "
                    "webapp/promo_standalone.py ops/servgo_monitor.py")
        run(remote, "systemctl daemon-reload")
        # Preserve an already-running independently managed service on failure.
        started = current_unit != "active"
        if started:
            run(remote, "systemctl enable --now " + UNIT)

        for i in range(20):
            code = run(remote, "curl -sS -o /dev/null -w '%{http_code}' "
                             "--max-time 3 http://127.0.0.1:18080/_promo_health 2>/dev/null || true")
            if code == "200":
                break
            time.sleep(2)
        else:
            raise RuntimeError("New independent promo service did not become healthy")

        for path, expected in [("/", "200"), ("/beauty", "200"),
                               ("/robots.txt", "200")]:
            code = run(remote, "curl -sS -o /dev/null -w '%{http_code}' "
                             "-H 'Host: promo.servgo.ru' --max-time 5 "
                             + shell("http://127.0.0.1:18080" + path))
            if code != expected:
                raise RuntimeError("New promo route mismatch " + path + ": " + code)

        if site_new != site_old:
            original_mode = stat.S_IMODE(sftp.stat(site_path).st_mode)
            put_atomic(sftp, site_path, site_new, original_mode)
            switched = True
            if run(remote, "nginx -t >/dev/null 2>&1 && echo ok") != "ok":
                raise RuntimeError("New nginx promo configuration invalid")
            run(remote, "systemctl reload nginx")

        for path in ("/", "/beauty", "/robots.txt"):
            code = run(remote, "curl -ksS -o /dev/null -w '%{http_code}' --max-time 6 "
                             "--resolve promo.servgo.ru:443:127.0.0.1 "
                             + shell("https://promo.servgo.ru" + path))
            if code != "200":
                raise RuntimeError("Live promo route unhealthy " + path + ": " + code)
        if run(remote, "systemctl is-active booking-bot.service") != "active":
            raise RuntimeError("Booking Telegram bot unexpectedly changed state")
        if run(remote, "curl -ksS -o /dev/null -w '%{http_code}' --max-time 5 "
                       "--resolve servgo.ru:443:127.0.0.1 https://servgo.ru/") != "200":
            raise RuntimeError("Main site changed unexpectedly")
        print("PROMO_ISOLATION_OK=true independent_port=18080 "
              "nginx_modified=promo_only booking_bot_untouched=true", flush=True)

        # Only after the independent website is healthy, install health monitoring.
        dry = run(remote, "cd " + shell(ROOT) + " && venv/bin/python "
                         "ops/servgo_monitor.py --check || true", 90)
        print("monitor_initial_health=" + dry[:4500], flush=True)
        # Deliverability test before enabling recurring checks.
        try:
            run(remote, "cd " + shell(ROOT) + " && venv/bin/python "
                        "ops/servgo_monitor.py --test-message", 35)
        except RuntimeError:
            print("monitor_alert_delivery=failed; timer_not_enabled=true", flush=True)
            return
        print("monitor_alert_delivery=ok", flush=True)
        run(remote, "systemctl daemon-reload && systemctl enable --now " + TIMER)
        print("MONITOR_ENABLED=true interval=2min", flush=True)
    except Exception:
        if switched and site_old is not None:
            try:
                put_atomic(sftp, site_path, site_old)
                run(remote, "nginx -t >/dev/null 2>&1 && systemctl reload nginx")
                print("nginx_rollback=ok", flush=True)
            except Exception:
                print("nginx_rollback=FAILED manual_recovery_required=true", flush=True)
        if started:
            try:
                run(remote, "systemctl disable --now " + UNIT + " || true")
            except Exception:
                pass
        for path in reversed(written):
            try:
                sftp.remove(path)
            except OSError:
                pass
        if written:
            try:
                run(remote, "systemctl daemon-reload")
            except Exception:
                pass
        raise
    finally:
        sftp.close()
        remote.close()


if __name__ == "__main__":
    main()
