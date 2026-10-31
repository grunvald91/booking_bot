"""Targeted, SHA-safe monitor hotfix. No nginx, bot or website changes."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BASE = "71bf49fc3b70355e8c0eabde419e8a6e743c5eb9"
REMOTE = "/opt/booking_bot/ops/servgo_monitor.py"


def main() -> None:
    from scripts.deploy_business_creation_and_reminders import connect, run
    from scripts.deploy_servgo_promo_monitor import read_optional, put_atomic
    token = os.environ.get("SERVGO_PASSWORD")
    if not token:
        raise RuntimeError("Missing SSH secret")
    old = subprocess.check_output(["git", "show", f"{BASE}:ops/servgo_monitor.py"], cwd=REPO)
    new = (REPO / "ops/servgo_monitor.py").read_bytes()
    client = connect(token)
    sftp = client.open_sftp()
    try:
        actual = read_optional(sftp, REMOTE)
        if actual not in (old, new):
            raise RuntimeError("Unreviewed monitor file drift; refusing overwrite")
        if actual == old:
            put_atomic(sftp, REMOTE, new)
            if read_optional(sftp, REMOTE) != new:
                put_atomic(sftp, REMOTE, old)
                raise RuntimeError("Monitor write verification failed")
        try:
            result = run(client,
                "cd /opt/booking_bot && venv/bin/python -m py_compile ops/servgo_monitor.py "
                "&& venv/bin/python ops/servgo_monitor.py --check", timeout=90)
        except Exception:
            if actual == old:
                put_atomic(sftp, REMOTE, old)
            raise
        print("MONITOR_HEALTHY=true", flush=True)
        print(result[:4500], flush=True)
        run(client, "systemctl start servgo-health-monitor.service")
        print("MONITOR_UPDATED=true service_timer_unchanged=true", flush=True)
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
