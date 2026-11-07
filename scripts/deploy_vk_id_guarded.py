"""Guarded, idempotent, scoped VK ID server release.

Preserves production-only changes: inserts only the two ORM classes, the
explicit VK merge hooks, and the FastAPI router; never replaces old source files.
Without APPLY=true, the same checks run but no server file/database changes.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import os
from pathlib import Path
import shlex
import time

from scripts.deploy_business_creation_and_reminders import ROOT, WEB_SERVICE, connect, run, wait_web_ready

APP_ROUTE = "web/api/routes/vk_auth.py"
MODELS = "database/models.py"
LINK = "database/account_link.py"
MAIN = "web/api/main.py"
FILES = (MODELS, LINK, MAIN, APP_ROUTE)
BACKUP_DIR = ROOT + "/.servgo-vk-releases"


def syntax(source: str) -> str:
    ast.parse(source)
    return source


def function(source: str, name: str) -> ast.AST:
    matches = [n for n in ast.parse(source).body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise RuntimeError("Unexpected or missing function: " + name)
    return matches[0]


def patch_models(live: str, reviewed: str) -> str:
    anchor = "class YandexTicket(Base):"
    start = "class VkIdentity(Base):"
    end = "class VkLoginTicket(Base):"
    if start in live or end in live:
        if start not in live or end not in live:
            raise RuntimeError("Partial VK ORM classes present")
        for name in ("VkIdentity", "VkLoginTicket"):
            expected = next(n for n in ast.parse(reviewed).body
                            if isinstance(n, ast.ClassDef) and n.name == name)
            present = next((n for n in ast.parse(live).body
                            if isinstance(n, ast.ClassDef) and n.name == name), None)
            if present is None or ast.dump(present, include_attributes=False) != ast.dump(expected, include_attributes=False):
                raise RuntimeError("Divergent existing VK ORM class")
        return live
    if live.count(anchor) != 1 or reviewed.count(start) != 1 or reviewed.count(anchor) != 1:
        raise RuntimeError("Unexpected Yandex/VK ORM layout")
    block = reviewed[reviewed.index(start):reviewed.index(anchor)]
    return syntax(live.replace(anchor, block + anchor, 1))


def patch_account_link(live: str, reviewed: str) -> str:
    if "async def merge_vk_account(" in live:
        # No partial repair of unknown production edits. Keep already deployed
        # source only when its VK-specific function is reviewed and identical.
        x = ast.get_source_segment(live, function(live, "merge_vk_account"))
        y = ast.get_source_segment(reviewed, function(reviewed, "merge_vk_account"))
        if ast.dump(ast.parse(x), include_attributes=False) != ast.dump(ast.parse(y), include_attributes=False):
            raise RuntimeError("Divergent existing merge_vk_account")
        if "from database.models import VkIdentity" not in ast.get_source_segment(live, function(live, "move_account_data")):
            raise RuntimeError("VK merge function exists, VK transfer hook absent")
        return live
    needle = "    await move_crm_contacts(db, source, target)\n"
    move_live = ast.get_source_segment(live, function(live, "move_account_data"))
    move_reviewed = ast.get_source_segment(reviewed, function(reviewed, "move_account_data"))
    if (move_live is None or move_reviewed is None or live.count(needle) != 1
            or "VkIdentity" in move_live or needle not in move_live):
        raise RuntimeError("Unexpected production move_account_data")
    pre_marker = "    from database.models import VkIdentity\n"
    post_marker = "    if vk_source is not None:\n        vk_source.user_id = target.id\n"
    if pre_marker not in move_reviewed or post_marker not in move_reviewed:
        raise RuntimeError("Reviewed VK account hook missing")
    pre = move_reviewed[move_reviewed.index(pre_marker):move_reviewed.index(needle)]
    post = post_marker
    added_function = ast.get_source_segment(reviewed, function(reviewed, "merge_vk_account"))
    if not added_function:
        raise RuntimeError("Reviewed merge_vk_account unavailable")
    updated = live.replace(needle, pre + needle + post, 1)
    updated = updated.rstrip() + "\n\n\n" + added_function + "\n"
    return syntax(updated)


def patch_main(live: str, reviewed: str) -> str:
    router_line = 'app.include_router(yandex_auth.router, prefix="/auth", tags=["auth"])\n'
    vk_line = 'app.include_router(vk_auth.router, prefix="/auth", tags=["auth"])\n'
    if vk_line in live:
        if "vk_auth" not in ast.get_source_segment(live, ast.parse(live).body[0]):
            # Import might not be the first AST statement; check source below.
            if "vk_auth" not in live.split("app.include_router(", 1)[0]:
                raise RuntimeError("VK router included but not imported")
        return live
    if live.count(router_line) != 1:
        raise RuntimeError("Missing unique Yandex include router anchor")
    lines = live.splitlines(keepends=True)
    imports = [i for i, line in enumerate(lines)
               if line.startswith("from .routes import ") and "yandex_auth" in line]
    if len(imports) != 1 or "vk_auth" in lines[imports[0]]:
        raise RuntimeError("Unexpected FastAPI router imports")
    lines[imports[0]] = lines[imports[0]].replace("yandex_auth", "yandex_auth, vk_auth", 1)
    updated = "".join(lines).replace(router_line, router_line + vk_line, 1)
    if reviewed.count(vk_line) != 1:
        raise RuntimeError("New router missing from reviewed main")
    return syntax(updated)


def read(sftp, path: str) -> bytes | None:
    try:
        with sftp.open(ROOT + "/" + path, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def remote_python(client, code: str, timeout=90) -> str:
    # Load live API systemd environment without exposing credential values.
    header = """
import os, pathlib, subprocess
pid = subprocess.check_output(['systemctl','show','-p','MainPID','--value',
                               'booking-web-api.service'], text=True).strip()
if not pid.isdecimal() or int(pid) < 2:
    raise RuntimeError('Booking API PID invalid')
for pair in pathlib.Path('/proc/' + pid + '/environ').read_bytes().split(bytes([0])):
    if b'=' in pair:
        name, _, value = pair.partition(b'=')
        os.environ[name.decode('utf-8')] = value.decode('utf-8')
"""
    return run(client, "cd " + shlex.quote(ROOT) +
               " && ./venv/bin/python -c " + shlex.quote(header + code), timeout)


def backup_database(client, path: str) -> None:
    backup_code = """
import os, subprocess, pathlib
from sqlalchemy.engine import make_url
from web.api.database import DATABASE_URL
url = make_url(DATABASE_URL)
if url.get_backend_name() != 'postgresql':
    raise RuntimeError('Expected PostgreSQL')
env = os.environ.copy()
if url.password:
    env['PGPASSWORD'] = url.password
if url.host:
    env['PGHOST'] = url.host
if url.port:
    env['PGPORT'] = str(url.port)
if url.username:
    env['PGUSER'] = url.username
if not url.database:
    raise RuntimeError('PostgreSQL database name missing')
dest = pathlib.Path(%r)
if dest.exists():
    raise RuntimeError('Snapshot filename collision')
subprocess.run(['pg_dump', '-Fc', '-f', str(dest), '-d', url.database],
               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, check=True, timeout=180)
if not dest.exists() or dest.stat().st_size < 128:
    raise RuntimeError('Database backup missing or empty')
print('DATABASE_BACKUP=verified')
""" % path
    remote_python(client, backup_code, 230)


def migrate(client, sql: str) -> None:
    code = """
import asyncio, base64
from sqlalchemy import text
from web.api.database import engine
sql = base64.b64decode(%r).decode('utf-8')
async def migrate():
    async with engine.begin() as conn:
        statements = '\\n'.join(line for line in sql.splitlines()
                               if not line.lstrip().startswith('--'))
        for statement in statements.split(';'):
            statement = statement.strip()
            if statement and statement.upper() not in ('BEGIN', 'COMMIT'):
                await conn.execute(text(statement))
        for table in ('vk_identities','vk_login_tickets'):
            result = await conn.execute(
                text("SELECT to_regclass(:n)"), {'n': table})
            if result.scalar() is None:
                raise RuntimeError('VK table missing after migration')
    await engine.dispose()
asyncio.run(migrate())
print('VK_SCHEMA=verified')
""" % base64.b64encode(sql.encode()).decode()
    out = remote_python(client, code, 110)
    if "VK_SCHEMA=verified" not in out:
        raise RuntimeError("VK migration check failed")


def main():
    apply = os.environ.get("APPLY", "false").lower() == "true"
    repo = Path(__file__).resolve().parents[1]
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("SERVER_SSH_PASSWORD not configured")
    reviewed = {path: (repo / path).read_text("utf-8") for path in FILES}
    sql = (repo / "migrations/add_vk_login.sql").read_text("utf-8")
    import re
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    if re.search(r"(?im)^\s*(?:DROP|DELETE|TRUNCATE|ALTER\s+TABLE\s+\S+\s+DROP)\b", statements):
        raise RuntimeError("Unexpected destructive SQL")
    client = connect(password)  # pinned SSH host fingerprint from shared helper
    sftp = client.open_sftp()
    stamp = str(int(time.time()))
    backup = BACKUP_DIR + "/" + stamp
    original = {}
    patched = {}
    touched = []
    prepared = False
    try:
        if run(client, "systemctl is-active " + WEB_SERVICE) != "active":
            raise RuntimeError("Booking API inactive; no release")
        if run(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:8000/health") != "200":
            raise RuntimeError("Booking API unhealthy; no release")
        for path in FILES:
            original[path] = read(sftp, path)
        if any(original[p] is None for p in (MODELS, LINK, MAIN)):
            raise RuntimeError("An existing server backend source file is missing")
        patched[MODELS] = patch_models(original[MODELS].decode(), reviewed[MODELS]).encode()
        patched[LINK] = patch_account_link(original[LINK].decode(), reviewed[LINK]).encode()
        patched[MAIN] = patch_main(original[MAIN].decode(), reviewed[MAIN]).encode()
        if original[APP_ROUTE] not in (None, reviewed[APP_ROUTE].encode()):
            raise RuntimeError("Unexpected live VK auth module")
        patched[APP_ROUTE] = reviewed[APP_ROUTE].encode()
        for path in FILES:
            if path.endswith(".py"):
                compile(patched[path], path, "exec")
            print("VK_RELEASE_FILE=" + path + " action=" +
                  ("unchanged" if patched[path] == original[path] else
                   ("create" if original[path] is None else "patch")), flush=True)
        # Verify the reviewed merge code cannot inadvertently replace a
        # production-only module or another auth provider.
        if not apply:
            print("VK_RELEASE_PREFLIGHT=passed production_untouched=true")
            return
        # Check backup utilities first, before changing schema or code.
        if run(client, "command -v pg_dump >/dev/null && echo yes") != "yes":
            raise RuntimeError("pg_dump missing; no release")
        run(client, "install -d -m 0700 " + shlex.quote(BACKUP_DIR) +
            " && install -d -m 0700 " + shlex.quote(backup))
        prepared = True
        backup_database(client, backup + "/postgres-before-vk.dump")
        # Back up all files before touching any. On rollback the newly
        # created VK route is removed and old source files are restored.
        for path in FILES:
            if original[path] is not None:
                dest = backup + "/" + path
                run(client, "install -d -m 0700 " + shlex.quote(str(Path(dest).parent)) +
                    " && cp -p -- " + shlex.quote(ROOT + "/" + path) + " " + shlex.quote(dest))
        migrate(client, sql)
        for path in FILES:
            if original[path] == patched[path]:
                continue
            dest = ROOT + "/" + path
            staged = dest + ".vk-stage-" + stamp
            with sftp.open(staged, "wb") as out:
                out.write(patched[path])
            sftp.chmod(staged, (sftp.stat(dest).st_mode & 0o777)
                       if original[path] is not None else 0o644)
            touched.append(path)
            sftp.posix_rename(staged, dest)
            if read(sftp, path) != patched[path]:
                raise RuntimeError("Server file mismatch after staging: " + path)
        run(client, "cd " + shlex.quote(ROOT) + " && ./venv/bin/python -m py_compile " +
            " ".join(shlex.quote(path) for path in FILES), 55)
        run(client, "systemctl restart " + WEB_SERVICE, 90)
        wait_web_ready(client)
        out = run(client, "curl -sS --max-time 7 http://127.0.0.1:8000/auth/vk/capabilities", 15)
        if '"available":false' not in out.replace(" ", "").lower() and '"available":true' not in out.replace(" ", "").lower():
            raise RuntimeError("New VK API capability endpoint failed")
        yandex = run(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 7 http://127.0.0.1:8000/auth/yandex/capabilities")
        if yandex != "200":
            raise RuntimeError("Existing Yandex SSO health changed")
        print("VK_RELEASE_APPLIED=true", "VK_API_CAPABILITIES="+out,
              "YANDEX_SSO=200", "DATABASE_BACKUP_ON_SERVER=true")
    except Exception:
        if touched:
            try:
                for path in reversed(touched):
                    dest = ROOT + "/" + path
                    if original[path] is None:
                        run(client, "rm -f -- " + shlex.quote(dest))
                    else:
                        run(client, "cp -p -- " + shlex.quote(backup + "/" + path) +
                            " " + shlex.quote(dest))
                run(client, "systemctl restart " + WEB_SERVICE, 90)
                wait_web_ready(client)
                print("VK_RELEASE_ROLLBACK=successful; additive VK tables left in place")
            except Exception:
                print("VK_RELEASE_ROLLBACK=failed_manual_recovery_required")
        raise
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
