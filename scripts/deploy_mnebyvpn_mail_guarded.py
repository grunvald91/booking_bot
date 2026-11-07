"""Guarded isolated ServGo deployment of MNEBYVPN signed SMTP code relay.

Default read-only SSH preflight. Explicit APPLY=true performs an additive schema
migration, encrypted-on-disk PostgreSQL dump, atomic code patch, API restart and
post-deploy health. Does not restart existing ServGo Telegram bot or touch nginx.
"""
from __future__ import annotations

import ast
import base64
import os
from pathlib import Path
import shlex
import time

from scripts.deploy_business_creation_and_reminders import ROOT, WEB_SERVICE, connect, run, wait_web_ready
from scripts.deploy_vk_id_guarded import remote_python

MODEL = "database/models.py"
API = "web/api/main.py"
EMAIL = "bot/services/email_notifications.py"
RELAY = "web/api/routes/mnebyvpn_mail.py"
FILES = (MODEL, API, EMAIL, RELAY)
BACKUPS = ROOT + "/.mnebyvpn-mail-releases"

def _syntax(source: str) -> str:
    ast.parse(source)
    return source

def _func(source: str, name: str) -> ast.AST:
    nodes = [n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise RuntimeError("Cannot identify a unique mail helper: " + name)
    return nodes[0]

def _equivalent(a: str, b: str) -> bool:
    return ast.dump(ast.parse(a), include_attributes=False) == ast.dump(ast.parse(b), include_attributes=False)

def patch_model(live: str, reviewed: str) -> str:
    start = "class MnebyvpnEmailDispatchNonce(Base):"
    end = "class EmailChallenge(Base):"
    if start in live:
        existing = next((n for n in ast.parse(live).body if isinstance(n, ast.ClassDef) and n.name == "MnebyvpnEmailDispatchNonce"), None)
        expected = next((n for n in ast.parse(reviewed).body if isinstance(n, ast.ClassDef) and n.name == "MnebyvpnEmailDispatchNonce"), None)
        if not existing or not expected or ast.dump(existing,include_attributes=False) != ast.dump(expected,include_attributes=False):
            raise RuntimeError("Live mail nonce model diverged")
        return live
    if reviewed.count(start)!=1 or reviewed.count(end)!=1 or live.count(end)!=1:
        raise RuntimeError("Unexpected ServGo email model anchors")
    block = reviewed[reviewed.index(start):reviewed.index(end)]
    return _syntax(live.replace(end,block+end,1))

def patch_api(live: str, reviewed: str) -> str:
    include = 'app.include_router(mnebyvpn_mail.router, prefix="/auth", tags=["mnebyvpn-mail"])'
    if include in live:
        if "mnebyvpn_mail" not in live.split("app.include_router(",1)[0]:
            raise RuntimeError("Mail relay registered but not imported")
        return _syntax(live)
    vk = 'app.include_router(vk_auth.router, prefix="/auth", tags=["auth"])'
    if live.count(vk)!=1 or reviewed.count(include)!=1:
        raise RuntimeError("Unexpected ServGo API route layout")
    lines = live.splitlines(keepends=True)
    found = [i for i,line in enumerate(lines) if line.startswith("from .routes import ") and "vk_auth" in line]
    if len(found)!=1 or "mnebyvpn_mail" in lines[found[0]]:
        raise RuntimeError("Unexpected ServGo route import")
    lines[found[0]] = lines[found[0]].replace("vk_auth,","vk_auth, mnebyvpn_mail,",1)
    return _syntax("".join(lines).replace(vk,vk+"\n"+include,1))

def patch_email(live: str, reviewed: str) -> str:
    reviewed_body = ast.get_source_segment(reviewed,_func(reviewed,"send_email"))
    if not reviewed_body or "from_override: str | None = None" not in reviewed_body:
        raise RuntimeError("Reviewed SMTP override unavailable")
    live_body = ast.get_source_segment(live,_func(live,"send_email"))
    if not live_body:
        raise RuntimeError("Current SMTP implementation not readable")
    if _equivalent(live_body,reviewed_body):
        return _syntax(live)
    # Preserve only trusted old ServGo send_email body shape. Other bot logic is
    # preserved verbatim, and changes outside this function are not overwritten.
    required = [
      "html_body: str | None = None,\n) -> bool:",
      '    from_name = os.getenv("SMTP_FROM_NAME", "ServGo")',
      '        logger.warning("Email delivery to %s failed: %s", to_email, exc)',
      'smtp.send_message(message)',
    ]
    if any(fragment not in live_body for fragment in required) or "from_override" in live_body:
        raise RuntimeError("Unknown SMTP sender implementation, manual review required")
    return _syntax(live.replace(live_body,reviewed_body,1))

def read(sftp, path: str) -> bytes|None:
    try:
        with sftp.open(ROOT+"/"+path,"rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None

def remote_db_backup(client, filename: str) -> None:
    code = r"""
import os, subprocess, pathlib
from sqlalchemy.engine import make_url
from web.api.database import DATABASE_URL
url=make_url(DATABASE_URL)
if url.get_backend_name()!='postgresql':
    raise RuntimeError('Require PostgreSQL for durable OTP')
env=os.environ.copy()
for key,value in [('PGHOST',url.host),('PGPORT',str(url.port) if url.port else None),
                  ('PGUSER',url.username),('PGPASSWORD',url.password)]:
    if value: env[key]=value
if not url.database: raise RuntimeError('Missing DB name')
backup=pathlib.Path(%r)
if backup.exists(): raise RuntimeError('Backup path collision')
subprocess.run(['pg_dump','-Fc','--file',str(backup),'--dbname',url.database],
    env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=200)
if backup.stat().st_size < 128: raise RuntimeError('PostgreSQL backup missing')
backup.chmod(0o600)
print('mail_db_backup=verified')
""" % filename
    result=remote_python(client,code,235)
    if "mail_db_backup=verified" not in result:
        raise RuntimeError("PostgreSQL backup failed")

def migrate(client,sql: str) -> None:
    payload=base64.b64encode(sql.encode()).decode()
    code = r"""
import asyncio,base64
from sqlalchemy import text
from web.api.database import engine
sql=base64.b64decode(%r).decode()
statements="\n".join(x for x in sql.splitlines() if not x.lstrip().startswith("--"))
async def main():
    async with engine.begin() as conn:
        for statement in statements.split(";"):
            statement=statement.strip()
            if statement and statement.upper() not in ("BEGIN","COMMIT"):
                await conn.execute(text(statement))
        exists=await conn.execute(text("SELECT to_regclass('public.mnebyvpn_email_dispatch_nonces')"))
        if not exists.scalar(): raise RuntimeError('OTP nonce table missing after migration')
    await engine.dispose()
asyncio.run(main())
print('mail_schema=verified')
""" % payload
    result=remote_python(client,code,105)
    if "mail_schema=verified" not in result:
        raise RuntimeError("OTP migration not verified")

def main() -> None:
    apply=os.getenv("APPLY","false").strip().lower()=="true"
    pwd=os.getenv("SERVGO_PASSWORD","")
    if not pwd: raise RuntimeError("Missing existing ServGo SSH credential")
    repo=Path(__file__).resolve().parents[1]
    reviewed={p:(repo/p).read_text(encoding="utf8") for p in FILES}
    sql=(repo/"migrations/add_mnebyvpn_email_gateway.sql").read_text()
    if any(keyword in sql.upper() for keyword in ("DROP TABLE","TRUNCATE ","DELETE FROM ","ALTER TABLE ")):
        raise RuntimeError("Destructive OTP migration not allowed")
    client=connect(pwd)
    sftp=client.open_sftp()
    stamp=str(int(time.time()))
    folder=BACKUPS+"/"+stamp
    originals={}
    staged={}
    touched=[]
    try:
        if run(client,"systemctl is-active "+WEB_SERVICE)!="active":
            raise RuntimeError("ServGo API not active")
        code=run(client,"curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/health")
        if code!="200":raise RuntimeError("ServGo API health was not 200")
        for path in FILES:
            originals[path]=read(sftp,path)
        if any(originals[path] is None for path in (MODEL,API,EMAIL)):
            raise RuntimeError("ServGo API source file missing")
        staged[MODEL]=patch_model(originals[MODEL].decode(),reviewed[MODEL]).encode()
        staged[API]=patch_api(originals[API].decode(),reviewed[API]).encode()
        staged[EMAIL]=patch_email(originals[EMAIL].decode(),reviewed[EMAIL]).encode()
        if originals[RELAY] is not None and not _equivalent(originals[RELAY].decode(),reviewed[RELAY]):
            raise RuntimeError("Unknown live MNEBYVPN relay module")
        staged[RELAY]=reviewed[RELAY].encode()
        for path in FILES:
            compile(staged[path],path,"exec")
            print("mail_release_file="+path+" mode="+
                ("unchanged" if originals[path]==staged[path] else
                 ("create" if originals[path] is None else "patch")),flush=True)
        print("mail_previous_api_health=200")
        if not apply:
            print("mail_preflight=passed production_untouched=true")
            return
        if run(client,"command -v pg_dump >/dev/null && echo yes")!="yes":
            raise RuntimeError("pg_dump unavailable")
        run(client,"install -d -m 0700 "+shlex.quote(BACKUPS)+" && install -d -m 0700 "+shlex.quote(folder))
        remote_db_backup(client,folder+"/postgres-before-mnebyvpn-mail.dump")
        for path in FILES:
            if originals[path] is None: continue
            dest=folder+"/"+path
            run(client,"install -d -m 0700 "+shlex.quote(str(Path(dest).parent))+
                " && cp -p -- "+shlex.quote(ROOT+"/"+path)+" "+shlex.quote(dest))
        migrate(client,sql)
        for path in FILES:
            if originals[path]==staged[path]:continue
            dest=ROOT+"/"+path
            tmp=dest+".mail-stage-"+stamp
            with sftp.open(tmp,"wb") as handle: handle.write(staged[path])
            sftp.chmod(tmp,(sftp.stat(dest).st_mode&0o777) if originals[path] is not None else 0o644)
            touched.append(path)
            sftp.posix_rename(tmp,dest)
            if read(sftp,path)!=staged[path]:
                raise RuntimeError("Uploaded mail source differs")
        run(client,"cd "+shlex.quote(ROOT)+" && ./venv/bin/python -m py_compile "+
            " ".join(shlex.quote(p) for p in FILES),50)
        run(client,"systemctl restart "+WEB_SERVICE,65)
        wait_web_ready(client)
        # 503 expected until dedicated shared HMAC secret is installed.
        status=run(client,
            "curl -s -o /dev/null -w '%{http_code}' --max-time 6 "+
            "http://127.0.0.1:8000/auth/mnebyvpn/email-code -X POST")
        if status not in ("401","400","503"):
            raise RuntimeError("Mail relay endpoint gave unexpected status: "+status)
        print("mail_release_applied=true api_health=200 mail_api_status="+status)
        print("mail_backup_on_server=true")
    except Exception:
        if touched:
            try:
                for path in reversed(touched):
                    dest=ROOT+"/"+path
                    if originals[path] is None:
                        run(client,"rm -f -- "+shlex.quote(dest))
                    else:
                        run(client,"cp -p -- "+shlex.quote(folder+"/"+path)+" "+shlex.quote(dest))
                run(client,"systemctl restart "+WEB_SERVICE,65)
                wait_web_ready(client)
                print("mail_rollback=restored_previous_files")
            except Exception:
                print("mail_rollback=manual_recovery_required")
        raise
    finally:
        sftp.close();client.close()

if __name__=="__main__":
    main()
