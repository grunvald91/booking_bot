"""Safely bind the existing Growth operator to the unique triple-linked ServGo owner.

One-time, human-authorized production administrative operation. No Business,
Growth Product or StudioBusinessLink rows are created, deleted or modified.
The only write is the existing Growth operator-link JSON, through its
file-locking atomic writer. Read-only preflight by default.
"""
from __future__ import annotations
import base64
import json
import os
import shlex
from scripts.deploy_business_creation_and_reminders import ROOT, connect

# This owner email was provided in the conversation and matched a verified
# email identity and matching Telegram+Yandex identity in the earlier audit.
TARGET_EMAIL_SHA256 = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"

OWNER_SCRIPT = r'''
import asyncio, hashlib, json, os
from sqlalchemy import select
from dotenv import load_dotenv
load_dotenv("/opt/booking_bot/.env")
from bot.config import DATABASE_URL as BOT_DATABASE_URL
os.environ.setdefault("DATABASE_URL", BOT_DATABASE_URL)
from web.api.database import async_session
from database.models import User, EmailIdentity, YandexIdentity

TARGET = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"
async def main():
    async with async_session() as db:
        emails = list((await db.scalars(select(EmailIdentity))).all())
        verified = [r for r in emails if isinstance(r.email, str) and
                    hashlib.sha256(r.email.strip().lower().encode()).hexdigest()==TARGET]
        if len(verified)!=1:
            raise RuntimeError("Exactly one verified email principal is required")
        user = await db.get(User, verified[0].user_id)
        if user is None or not user.telegram_id or not isinstance(user.telegram_id, int):
            raise RuntimeError("Telegram principal is missing")
        if (user.username or "").lstrip("@").casefold() != "grunvald":
            raise RuntimeError("Telegram handle does not match")
        digits = "".join(c for c in (user.phone or "") if c.isdigit())
        if not digits.endswith("1399"):
            raise RuntimeError("Current user phone does not match expected suffix")
        yandex = list((await db.scalars(select(YandexIdentity).where(
            YandexIdentity.user_id==user.id))).all())
        if len(yandex)!=1:
            raise RuntimeError("Exactly one verified Yandex principal is required")
        print(json.dumps({"ok":True,"user_id":user.id,"triple_verified":True}))
asyncio.run(main())
'''

GROWTH_SCRIPT = r'''
import json, os, sys
from sqlalchemy import select
from app.core.config import get_settings
from app.core.studio_operator_links import bind_operator, linked_operator, _path
from app.api.content_studio_auth import credential_fingerprint, _load_users
from app.models.domain import Product
from app.sso.models import StudioBusinessLink
from app.db.session import SessionLocal

uid = int(sys.argv[1])
apply = sys.argv[2] == "apply"
if uid <= 0:
    raise RuntimeError("Invalid principal ID")
settings = get_settings()
users = _load_users(settings)
with SessionLocal() as db:
    servgo = list(db.scalars(select(Product).where(Product.slug == "servgo")))
    if len(servgo)!=1 or (servgo[0].name or "").strip().casefold()!="servgo":
        raise RuntimeError("Existing ServGo Growth product is not unique")
    linked_business = list(db.scalars(select(StudioBusinessLink).where(
        StudioBusinessLink.product_id == servgo[0].id)))
    if linked_business:
        raise RuntimeError("Existing ServGo Growth project unexpectedly mapped to BookingBot")

# Choose only a currently configured, effective platform operator (never a
# company-scoped account). Prefer the uniquely explicit configured operator,
# then uniquely permitted tune operator, then unique configured operator.
eligible = {}
for login, info in users.items():
    if not isinstance(info, dict) or info.get("role")!="admin":
        continue
    active = credential_fingerprint(settings, users, login)
    if active is not None and active[1] is None:
        eligible[login] = active[0]
if settings.studio_htpasswd_file:
    hashes = settings.studio_htpasswd_file.read_text(encoding="utf-8").splitlines()
    for row in hashes:
        if not row or row.startswith("#") or ":" not in row:
            continue
        name = row.split(":",1)[0]
        active = credential_fingerprint(settings, users, name)
        if active is not None and active[1] is None:
            eligible[name] = active[0]
if settings.studio_admin_username:
    name = settings.studio_admin_username
    active = credential_fingerprint(settings, users, name)
    if active is not None and active[1] is None:
        eligible[name] = active[0]
if not eligible:
    raise RuntimeError("No configured administrator-level Growth identity")

explicit = settings.studio_admin_username if settings.studio_admin_username in eligible else None
tune = {x.strip() for x in (settings.studio_tune_usernames or "").split(",") if x.strip()}
tune_candidates = sorted(set(eligible).intersection(tune))
if explicit:
    name = explicit
    selected_by = "explicit_admin_setting"
elif len(tune_candidates)==1:
    name=tune_candidates[0]
    selected_by="unique_tune_operator"
elif len(eligible)==1:
    name=next(iter(eligible))
    selected_by="unique_configured_operator"
else:
    # No account-name guessing or platform-wide elevation in an ambiguous setup.
    print(json.dumps({"ok":False,"reason":"ambiguous_operator",
                      "eligible_count":len(eligible),
                      "tune_candidate_count":len(tune_candidates)}))
    raise RuntimeError("Multiple Growth operators need explicit selection")

# Existing links must not be silently overwritten, even when credentials
# changed. Avoid logging filenames, identities or secret fingerprints.
file = _path(settings)
try:
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data,dict):
        raise RuntimeError("Invalid operator links")
except FileNotFoundError:
    data={}
entry = data.get(str(uid))
already_valid = linked_operator(settings,uid,users)
if entry is not None and already_valid!=name:
    raise RuntimeError("A different or stale Growth operator binding exists")
if apply and entry is None:
    bind_operator(settings,uid,name,eligible[name])
if apply and linked_operator(settings,uid,users)!=name:
    raise RuntimeError("Growth operator binding could not be verified")
print(json.dumps({"ok":True,"mode":"applied" if apply else "preflight",
                  "owner_identity_verified_external":True,
                  "selected_by":selected_by,
                  "eligible_admin_count":len(eligible),
                  "already_linked":already_valid==name,
                  "existing_growth_project_reused":True,
                  "existing_business_records_changed":False}))
'''

def invoke(client, script:str, args:list[str], docker:bool=False) -> dict:
    payload=base64.b64encode(script.encode("utf-8")).decode("ascii")
    code="import base64;exec(compile(base64.b64decode("+repr(payload)+"),'<servgo-operator-binding>','exec'))"
    command=("docker exec ai-growth-os-api-1 python -c " if docker
             else "cd "+shlex.quote(ROOT)+" && ./venv/bin/python -c ")
    command+=shlex.quote(code)+"".join(" "+shlex.quote(a) for a in args)
    _,stdout,stderr=client.exec_command(command,timeout=90)
    output=stdout.read().decode("utf-8","replace").strip()
    status=stdout.channel.recv_exit_status()
    if status!=0:
        # Only a structured, non-sensitive reason; never expose raw tracebacks.
        if "ambiguous_operator" in output:
            raise RuntimeError("Ambiguous Growth operator configuration, binding not changed")
        raise RuntimeError("Production identity verification or binding failed (private diagnostics hidden)")
    try:
        record=json.loads(output.splitlines()[-1])
        if record.get("ok") is not True:
            raise ValueError("not ok")
        return record
    except (ValueError,TypeError,IndexError) as exc:
        raise RuntimeError("Unexpected structured result") from exc

def main():
    if not os.getenv("SERVGO_PASSWORD"):
        raise RuntimeError("SSH secret unavailable")
    apply=os.getenv("APPLY","false").casefold()=="true"
    client=connect(os.environ["SERVGO_PASSWORD"])
    try:
        owner=invoke(client,OWNER_SCRIPT,[])
        if not owner.get("triple_verified"):
            raise RuntimeError("Unverified ServGo principal")
        result=invoke(client,GROWTH_SCRIPT,[str(owner["user_id"]),"apply" if apply else "check"],docker=True)
        # No UID or credentials reach logs.
        print(json.dumps(result,sort_keys=True))
    finally:
        client.close()
if __name__=="__main__":
    main()
