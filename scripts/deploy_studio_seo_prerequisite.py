"""Resolve the reviewed SEO API prerequisite of the Studio frontend release.

Only the exact historical version (or an AST-identical file) is accepted.
Unknown production code is never overwritten. No database or company changes.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import shlex
import stat
import subprocess
import time

from scripts.deploy_business_creation_and_reminders import ROOT, WEB_SERVICE, connect, put, run, wait_web_ready
from scripts.deploy_studio_canonical_sso import verify_account_routes

PATH = "web/api/routes/seo_pages.py"
BEFORE = "24d47972f516a28f67342fbe27952fc699852979"
AFTER = "aef2dffbdb4222587295c9564df716558f840a80"


def ast_equal(left: bytes, right: bytes) -> bool:
    try:
        return ast.dump(ast.parse(left)) == ast.dump(ast.parse(right))
    except (SyntaxError, UnicodeError, ValueError):
        return False


def plan(current: bytes, baseline: bytes, reviewed: bytes, candidate: bytes) -> str:
    if current == candidate:
        return "already"
    if candidate != reviewed:
        raise ValueError("SEO candidate is not the reviewed historical change")
    if ast_equal(current, reviewed) or ast_equal(current, baseline):
        return "update"
    raise ValueError("Unrecognized live SEO code; refusing to overwrite")


def blob(repo: Path, revision: str) -> bytes:
    return subprocess.check_output(["git", "show", revision + ":" + PATH], cwd=repo)


def read(sftp, path: str) -> bytes:
    with sftp.open(path, "rb") as handle:
        return handle.read()


def release() -> None:
    repo = Path(__file__).resolve().parents[1]
    candidate = (repo / PATH).read_bytes()
    compile(candidate, PATH, "exec")
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("Missing production credential")
    client = connect(password)
    sftp = client.open_sftp()
    remote = ROOT + "/" + PATH
    backup = remote + ".studio-seo-backup-" + str(time.time_ns())
    changed = False
    try:
        if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
            raise RuntimeError("Booking API inactive")
        wait_web_ready(client)
        current = read(sftp, remote)
        if current == candidate:
            print("STUDIO_SEO_PREREQUISITE=ALREADY_ACTIVE")
            return
        baseline, reviewed = blob(repo, BEFORE), blob(repo, AFTER)
        print("seo_current_sha256=" + hashlib.sha256(current).hexdigest(),
              "seo_baseline_sha256=" + hashlib.sha256(baseline).hexdigest(),
              "seo_reviewed_sha256=" + hashlib.sha256(reviewed).hexdigest(), flush=True)
        if plan(current, baseline, reviewed, candidate) != "update":
            raise RuntimeError("Unexpected SEO rollout decision")
        if os.environ.get("APPLY", "false").lower() != "true":
            print("STUDIO_SEO_PREREQUISITE=PREFLIGHT_OK")
            return
        mode = stat.S_IMODE(sftp.stat(remote).st_mode)
        run(client, "cp -p -- " + shlex.quote(remote) + " " + shlex.quote(backup))
        if read(sftp, backup) != current or read(sftp, remote) != current:
            raise RuntimeError("SEO backup or live file changed unexpectedly")
        changed = True
        put(sftp, remote, candidate, mode)
        run(client, "python3 -m py_compile " + shlex.quote(remote))
        run(client, "systemctl restart " + WEB_SERVICE, timeout=70)
        wait_web_ready(client)
        if read(sftp, remote) != candidate:
            raise RuntimeError("SEO prerequisite byte verification failed")
        verify_account_routes(client, (repo / "web/api/routes/studio_sso.py").read_text())
        print("STUDIO_SEO_PREREQUISITE=DEPLOYED;API_HEALTH=200")
    except Exception:
        if changed:
            run(client, "cp -p -- " + shlex.quote(backup) + " " + shlex.quote(remote))
            run(client, "systemctl restart " + WEB_SERVICE, timeout=70)
            wait_web_ready(client)
            print("STUDIO_SEO_PREREQUISITE=ROLLED_BACK")
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    release()
