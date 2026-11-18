"""Guarded one-file BookingBot public company GEO route update.

Read-only preflight by default. APPLY=true changes exactly the declared route,
only if production bytes exactly match the reviewed PR #160 baseline.
No migrations, other routes, nginx, flags, or customer data are changed.
"""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import time

from scripts.deploy_business_creation_and_reminders import (
    ROOT, WEB_SERVICE, connect, run, put, wait_web_ready,
)

BASE_COMMIT = "24dbedee490b62302ac276113ccf9891d7980390"
SOURCE_PATH = "web/api/routes/seo_pages.py"
REMOTE_PATH = ROOT + "/" + SOURCE_PATH
BACKUP_ROOT = ROOT + "/.geo-company-ssr-backups"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state(current: bytes | None, previous: bytes, desired: bytes) -> str:
    if current == desired:
        return "already"
    if current == previous:
        return "safe_update"
    return "conflict"


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    apply = os.environ.get("APPLY", "").lower() == "true"
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("Operator server secret is unavailable")
    desired = (repo / SOURCE_PATH).read_bytes()
    compile(desired, SOURCE_PATH, "exec")
    baseline = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:{SOURCE_PATH}"],
        cwd=repo, capture_output=True, check=False,
    )
    if baseline.returncode != 0 or not baseline.stdout:
        raise RuntimeError("Reviewed baseline unavailable; refusing production action")

    client = connect(password)
    sftp = client.open_sftp()
    backup = None
    touched = False
    original = None
    try:
        if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
            raise RuntimeError("Booking web API is not active")
        health = run(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8000/health")
        if health != "200":
            raise RuntimeError("Existing API health check failed")
        try:
            with sftp.open(REMOTE_PATH, "rb") as handle:
                original = handle.read()
        except FileNotFoundError:
            raise RuntimeError("Production route is missing; refusing to create it") from None
        assessment = state(original, baseline.stdout, desired)
        print("geo_route_preflight", assessment,
              "running_sha256", digest(original)[:20],
              "baseline_sha256", digest(baseline.stdout)[:20],
              "desired_sha256", digest(desired)[:20],
              "api_health", health, flush=True)
        if assessment == "conflict":
            raise RuntimeError("Production version diverged; refusing to overwrite")
        if assessment == "already":
            print("geo_route_already_deployed=true", flush=True)
            return
        if not apply:
            print("geo_route_preflight_ok=true production_untouched=true", flush=True)
            return
        stamp = str(int(time.time()))
        backup = BACKUP_ROOT + "/" + stamp + ".seo_pages.py"
        run(client, "install -d -m 0700 " + shlex.quote(BACKUP_ROOT) +
            " && cp -p " + shlex.quote(REMOTE_PATH) + " " + shlex.quote(backup))
        stat = sftp.stat(REMOTE_PATH)
        touched = True
        put(sftp, REMOTE_PATH, desired, stat.st_mode & 0o777)
        with sftp.open(REMOTE_PATH, "rb") as handle:
            if digest(handle.read()) != digest(desired):
                raise RuntimeError("Production file mismatch after update")
        run(client, "cd " + shlex.quote(ROOT) +
            " && ./venv/bin/python -m py_compile " + shlex.quote(SOURCE_PATH), 45)
        run(client, "systemctl restart " + WEB_SERVICE, 65)
        wait_web_ready(client)
        print("geo_route_release_ok=true files_changed=1 backup_kept=true", flush=True)
    except Exception:
        if touched:
            try:
                run(client, "cp -p " + shlex.quote(backup) +
                    " " + shlex.quote(REMOTE_PATH) +
                    " && systemctl restart " + WEB_SERVICE, 65)
                wait_web_ready(client)
                with sftp.open(REMOTE_PATH, "rb") as handle:
                    if handle.read() != original:
                        raise RuntimeError("Rollback bytes mismatch")
                print("geo_route_rollback_ok=true", flush=True)
            except Exception as rollback_error:
                print("geo_route_rollback_failed=true", flush=True)
                raise RuntimeError("Company SSR route release failed and rollback failed") from rollback_error
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
