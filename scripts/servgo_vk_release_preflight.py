"""Read-only production preflight for a scoped VK ID release.

No mutation, no credential values in logs. Fails closed when SSH/DB isn't ready.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex

from scripts.deploy_business_creation_and_reminders import ROOT, WEB_SERVICE, connect, run

FILES = (
    "database/models.py",
    "database/account_link.py",
    "web/api/main.py",
    "web/api/routes/vk_auth.py",
    "migrations/add_vk_login.sql",
)

CHECK_DB = """
import asyncio, json, shutil
from sqlalchemy import text
from web.api.database import engine
async def check():
    async with engine.connect() as c:
        result = {}
        for table in ('users', 'vk_identities', 'vk_login_tickets'):
            r = await c.execute(text("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=:name)"), {'name':table})
            result[table] = bool(r.scalar())
        print('DB_SCHEMA=' + json.dumps(result, sort_keys=True))
    await engine.dispose()
asyncio.run(check())
print('PG_DUMP_AVAILABLE=' + str(bool(shutil.which('pg_dump'))).lower())
"""


def sha(value: bytes | None) -> str:
    return hashlib.sha256(value).hexdigest() if value is not None else "absent"


def main():
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("Required SSH secret is missing")
    repo = Path(__file__).resolve().parents[1]
    client = connect(password)
    sftp = client.open_sftp()
    try:
        if run(client, "systemctl is-active booking-web-api.service") != "active":
            raise RuntimeError("Booking API service is not active")
        health = run(client, "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/health")
        print("BOOKING_API_HEALTH=" + health)
        if health != "200":
            raise RuntimeError("Booking API is not healthy")
        for path in FILES:
            current = None
            try:
                with sftp.open(ROOT + "/" + path, "rb") as handle:
                    current = handle.read()
            except FileNotFoundError:
                pass
            local = (repo / path).read_bytes()
            status = "ABSENT" if current is None else ("CURRENT_MAIN" if sha(current) == sha(local) else "DRIFT_FROM_MAIN")
            print("SOURCE_" + path.replace("/", "_").replace(".", "_") + "=" + status)
        # The SSH shell does not inherit systemd EnvironmentFile values.
        # Bring the live API process environment into this one probe process;
        # never send its values back to the runner or print them.
        db_probe = (
            "import os,pathlib,subprocess,shutil,ast; "
            "pid=subprocess.check_output(['systemctl','show','-p','MainPID','--value',"
            "'booking-web-api.service'],text=True).strip(); "
            "pairs=pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(bytes([0])); "
            "[(os.environ.__setitem__(k.decode(),v.decode())) for p in pairs "
            "if b'=' in p for k,_,v in [p.partition(b'=')] "
            "if k.decode() in {'DATABASE_URL','DB_TYPE','DB_HOST','DB_PORT',"
            "'DB_NAME','DB_USER','DB_PASSWORD','BOT_TOKEN','JWT_SECRET'}]; "
            "print('DB_ENV_AVAILABLE='+str(bool(os.environ.get('DATABASE_URL') "
            "or os.environ.get('DB_PASSWORD'))).lower()); "
            "print('PG_DUMP_AVAILABLE='+str(bool(shutil.which('pg_dump'))).lower())"
            + "\ntry:\n" + "\n".join("    " + line for line in CHECK_DB.strip().splitlines())
            + "\nexcept Exception as exc:\n    print('DB_PROBE_ERROR='+type(exc).__name__)\n"
        )
        print(run(client, "cd " + shlex.quote(ROOT) + " && ./venv/bin/python -c " + shlex.quote(db_probe), 45))
        structure_probe = (
            "import ast,pathlib; root=pathlib.Path('/opt/booking_bot'); "
            "plans=[('database/models.py',('VkIdentity','VkLoginTicket','YandexIdentity')), "
            "('database/account_link.py',('move_account_data','merge_vk_account','merge_yandex_account')), "
            "('web/api/main.py',('vk_auth','yandex_auth'))]; "
            "[(print('CODE_'+p.replace('/','_')+'_'+name+'='+str(name in "
            "ast.parse((root/p).read_text()).__dict__.get('body',[]) or "
            "name in (root/p).read_text()).lower())) "
            "for p,names in plans for name in names]"
        )
        print(run(client, "python3 -c " + shlex.quote(structure_probe), 30))
        # Query only booleans: secrets are neither printed nor copied to Actions.
        process_check = (
            "import pathlib,subprocess; "
            "pid=subprocess.check_output(['systemctl','show','-p','MainPID','--value',"
            "'booking-web-api.service'],text=True).strip(); "
            "pairs=pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\\0'); "
            "keys={p.partition(b'=')[0].decode('utf-8','ignore') for p in pairs if b'=' in p}; "
            "print('VK_APP_ID_IN_PROCESS='+str('SERVGO_VK_ID_APP_ID' in keys).lower()); "
            "print('JWT_SECRET_IN_PROCESS='+str('JWT_SECRET' in keys).lower()); "
            "print('STUDIO_SSO_SECRET_IN_PROCESS='+str('STUDIO_SSO_SECRET' in keys).lower())"
        )
        print(run(client, "python3 -c " + shlex.quote(process_check), 30))
        print("PRODUCTION_MUTATED=false")
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
