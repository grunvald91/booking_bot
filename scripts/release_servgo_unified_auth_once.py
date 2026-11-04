"""One-time guarded 2026-11-04 ServGo Studio authentication backend release.

The normal frontend deploy does not install web/api handlers. Compare each
production file to the exact pre-PR main baseline (including known AST-only
SSO reshuffling), refuse unknown drift, back up, atomically replace only these
five files, restart the API, and roll back on any failure. Read-only by default.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import time

from scripts.deploy_business_creation_and_reminders import (
    ROOT, WEB_SERVICE, connect, put, run, wait_web_ready,
)
from scripts.deploy_servgo_frontend_atomic import backend_equivalent

BASE_SHA = "e710af9fc29c4de6f0a7551e876c8c26d0328be5"
FILES = (
    "web/api/routes/auth.py",
    "web/api/routes/email_auth.py",
    "web/api/routes/yandex_auth.py",
    "web/api/routes/studio_sso.py",
    "web/api/studio_identity.py",
)
NEW_FILES = frozenset({"web/api/studio_identity.py"})
BACKUP_ROOT = ROOT + "/.servgo-unified-auth-backups"
REPO = Path(__file__).resolve().parent.parent


def digest(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else "absent"


def old_file(path: str) -> bytes | None:
    p = subprocess.run(
        ["git", "show", f"{BASE_SHA}:{path}"],
        cwd=REPO, capture_output=True, check=False,
    )
    if p.returncode:
        if path in NEW_FILES:
            return None
        raise RuntimeError("Missing reviewed baseline: " + path)
    return p.stdout


def allowed_change(path: str, live: bytes | None, old: bytes | None, new: bytes) -> str:
    if live == new:
        return "already"
    if live is None:
        return "create" if old is None and path in NEW_FILES else "conflict"
    if old is None:
        return "conflict"
    if live == old:
        return "update"
    # Cosmetic / comment-only production edits are safe: no executable AST drift.
    try:
        if ast.dump(ast.parse(live), include_attributes=False) == ast.dump(
            ast.parse(old), include_attributes=False
        ):
            return "update"
    except (SyntaxError, UnicodeError, ValueError):
        return "conflict"
    # The server's canonical SSO patch may place two unchanged functions at
    # the end. Only the already-reviewed precise AST equivalence is accepted.
    if path == "web/api/routes/studio_sso.py" and backend_equivalent(path, live, old):
        return "update"
    return "conflict"


def read(sftp, target: str) -> bytes | None:
    try:
        with sftp.open(target, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def preflight_services(client) -> None:
    if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
        raise RuntimeError("ServGo API service is not active")
    if run(client, "nginx -t >/dev/null 2>&1 && echo ok") != "ok":
        raise RuntimeError("Production nginx syntax is invalid")
    for port in (8000, 8091):
        status = run(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 6 "
                     + f"http://127.0.0.1:{port}/health || true")
        if status != "200":
            raise RuntimeError(f"Health failed on loopback port {port}: {status}")
    # Require the Growth *new* SSO implementation and enabled same-origin
    # identity binding before changing BookingBot; do not read any secret.
    marker = run(
        client,
        "docker exec ai-growth-os-api-1 python -c "
        + shlex.quote(
            'from app.sso.tickets import CANONICAL_ORIGIN; '
            'from app.core.config import get_settings; '
            's=get_settings(); '
            'print(CANONICAL_ORIGIN + " enabled=" + str(s.studio_servgo_gateway_enabled).lower())'
        ),
        20,
    )
    if marker.strip() != "https://servgo.ru enabled=true":
        raise RuntimeError("Growth canonical gateway is not enabled on the new release")
    # A 303 here is the canonical Growth handler redirecting to ServGo login;
    # an SPA fallback 200 or standalone legacy form 200 must not pass.
    route = run(
        client,
        "curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "
        "--resolve servgo.ru:443:127.0.0.1 "
        "-H 'Accept: text/html' https://servgo.ru/studio/login",
    )
    if route != "303":
        raise RuntimeError("Canonical Growth HTTPS gateway is not ready (studio login HTTP " + route + ")")
    print("growth_gateway_preflight=ok", flush=True)


def main() -> None:
    secret = os.environ.get("SERVGO_PASSWORD", "")
    if not secret:
        raise RuntimeError("SERVER_SSH_PASSWORD is missing")
    apply = os.environ.get("APPLY", "false").strip().lower() == "true"
    expected = {path: (REPO / path).read_bytes() for path in FILES}
    previous = {path: old_file(path) for path in FILES}
    for path, value in expected.items():
        compile(value, path, "exec")
    if b'"origin": CANONICAL_STUDIO_URL' not in expected["web/api/routes/studio_sso.py"]:
        raise RuntimeError("New SSO ticket is not bound to canonical origin")
    client = connect(secret)
    sftp = client.open_sftp()
    original: dict[str, bytes | None] = {}
    actions: dict[str, str] = {}
    modes: dict[str, int] = {}
    touched: list[str] = []
    backup_dir = BACKUP_ROOT + "/" + str(int(time.time()))
    try:
        preflight_services(client)
        for path in FILES:
            target = ROOT + "/" + path
            live = read(sftp, target)
            original[path] = live
            if live is not None:
                modes[path] = sftp.stat(target).st_mode & 0o777
            state = allowed_change(path, live, previous[path], expected[path])
            actions[path] = state
            print(f"auth_backend={path} action={state} live_sha={digest(live)[:16]} "
                  f"desired_sha={digest(expected[path])[:16]}", flush=True)
        conflicts = [p for p in FILES if actions[p] == "conflict"]
        if conflicts:
            raise RuntimeError("Unknown production drift, refusing overwrite: " + ", ".join(conflicts))
        todo = [p for p in FILES if actions[p] in ("update", "create")]
        if not apply:
            print(f"preflight_ok=true would_deploy={len(todo)} production_untouched=true")
            return
        if not todo:
            print("auth_backend_already_deployed=true")
            return
        run(client, "install -d -m 0700 " + shlex.quote(BACKUP_ROOT) + " "
            + shlex.quote(backup_dir))
        # Back up EVERYTHING before starting the first write.
        for path in todo:
            if original[path] is not None:
                backup = backup_dir + "/" + path
                run(client, "install -d -m 0700 " + shlex.quote(str(Path(backup).parent))
                    + " && cp -p " + shlex.quote(ROOT + "/" + path)
                    + " " + shlex.quote(backup))
        for path in todo:
            target = ROOT + "/" + path
            run(client, "install -d -m 0755 " + shlex.quote(str(Path(target).parent)))
            touched.append(path)
            put(sftp, target, expected[path], modes.get(path, 0o644))
            if digest(read(sftp, target)) != digest(expected[path]):
                raise RuntimeError("Readback SHA mismatch: " + path)
        run(client, "cd " + shlex.quote(ROOT)
            + " && ./venv/bin/python -m py_compile "
            + " ".join(shlex.quote(p) for p in todo if p.endswith(".py")), 35)
        run(client, "systemctl restart " + WEB_SERVICE, 65)
        wait_web_ready(client)
        endpoint = run(
            client,
            "curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
            "http://127.0.0.1:8000/internal/studio/businesses?user_id=0",
        )
        if endpoint != "403":
            raise RuntimeError("Internal Studio API unexpectedly public: HTTP " + endpoint)
        print(f"auth_backend_deployed=true changed={len(todo)} "
              f"backup_dir={backup_dir} api_health=200 internal_auth=403", flush=True)
    except BaseException:
        if touched:
            try:
                for path in reversed(touched):
                    target = ROOT + "/" + path
                    if original[path] is None:
                        run(client, "rm -f -- " + shlex.quote(target))
                    else:
                        backup = backup_dir + "/" + path
                        run(client, "cp -p -- " + shlex.quote(backup)
                            + " " + shlex.quote(target))
                run(client, "systemctl restart " + WEB_SERVICE, 65)
                wait_web_ready(client)
                print("auth_backend_rollback=ok", flush=True)
            except Exception as e:
                print("auth_backend_rollback=FAILED_MANUAL_RECOVERY", flush=True)
                raise RuntimeError("Auth rollout and rollback both failed") from e
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
