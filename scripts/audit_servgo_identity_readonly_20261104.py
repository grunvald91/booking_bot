"""One-time read-only audit of ServGo identity mapping for an owner report.

Queries only known account signals, never changes user/organisation records,
and never prints phone numbers, email addresses, Telegram IDs, Yandex IDs,
passwords, tokens or real database primary keys.
"""
from __future__ import annotations

import base64
import hashlib
import os
import shlex

from scripts.deploy_business_creation_and_reminders import ROOT, connect

# SHA256 of an email address that the owner volunteered for this investigation.
# Never print or store the cleartext address in the repository or Actions logs.
EMAIL_SHA256 = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"
PHONE_LAST4 = "1399"
TELEGRAM_USERNAME = "grunvald"

REMOTE = r'''
import asyncio, hashlib, json, os, subprocess
from collections import defaultdict
from sqlalchemy import select
from dotenv import load_dotenv
load_dotenv("/opt/booking_bot/.env")
from bot.config import DATABASE_URL as BOT_DATABASE_URL
os.environ.setdefault("DATABASE_URL", BOT_DATABASE_URL)
from web.api.database import async_session
from database.models import User, EmailIdentity, YandexIdentity, Business, BusinessOwner, UserAccountMerge

TARGET_EMAIL_HASH = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"
PHONE_SUFFIX = "1399"
TG_HANDLE = "grunvald"
def email_target(value):
    return bool(value and hashlib.sha256(value.strip().lower().encode()).hexdigest() == TARGET_EMAIL_HASH)
def phone_target(value):
    return bool(value and "".join(c for c in value if c.isdigit()).endswith(PHONE_SUFFIX))
async def run():
    async with async_session() as db:
        users = list((await db.execute(select(User.id, User.telegram_id, User.phone, User.email, User.username))).all())
        emails = list((await db.execute(select(EmailIdentity.user_id, EmailIdentity.email))).all())
        yandex = list((await db.execute(select(YandexIdentity.user_id, YandexIdentity.email, YandexIdentity.phone))).all())
        businesses = list((await db.execute(select(Business.id, Business.owner_id, Business.name))).all())
        owner_rows = list((await db.execute(select(BusinessOwner.user_id, BusinessOwner.business_id))).all())
        merges = list((await db.execute(select(UserAccountMerge.source_user_id, UserAccountMerge.target_user_id))).all())
    signals = defaultdict(set)
    user_data = {}
    for row in users:
        user_data[row.id] = row
        if email_target(row.email): signals[row.id].add("contact_email_match_unverified")
        if phone_target(row.phone): signals[row.id].add("user_phone_suffix")
        if row.telegram_id and row.telegram_id > 0 and (row.username or "").lstrip("@").casefold() == TG_HANDLE:
            signals[row.id].add("telegram_username_match")
    for row in emails:
        if email_target(row.email): signals[row.user_id].add("verified_email_login")
    for row in yandex:
        if email_target(row.email): signals[row.user_id].add("yandex_confirmed_email")
        if phone_target(row.phone): signals[row.user_id].add("yandex_confirmed_phone_suffix")
    ownership = defaultdict(set)
    tags = defaultdict(set)
    for b in businesses:
        ownership[b.owner_id].add(b.id)
        label=(b.name or "").casefold()
        if "автоточк" in label:
            tags[b.owner_id].add("autotochka")
            signals[b.owner_id].add("named_business_autotochka")
        if "яхт" in label:
            tags[b.owner_id].add("yacht")
            signals[b.owner_id].add("named_business_yacht")
    for member in owner_rows:
        ownership[member.user_id].add(member.business_id)
        for b in businesses:
            if b.id == member.business_id:
                label=(b.name or "").casefold()
                if "автоточк" in label:
                    tags[member.user_id].add("autotochka")
                    signals[member.user_id].add("named_business_autotochka")
                if "яхт" in label:
                    tags[member.user_id].add("yacht")
                    signals[member.user_id].add("named_business_yacht")
    verified_email_users={r.user_id for r in emails if email_target(r.email)}
    yandex_users={r.user_id for r in yandex}
    all_email_users={r.user_id for r in emails}
    # Show whether ServGo already exists as a business globally, not merely as a Growth product.
    servgo_rows = [row for row in businesses if (row.name or "").strip().casefold() == "servgo"]
    account_ids=sorted(signals)
    # Growth has its own company catalog. Compare it to ServGo's verified
    # business memberships without leaking any ID or sensitive user field.
    growth_code = """
import json
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.sso.models import StudioBusinessLink
from app.models.domain import Product
with SessionLocal() as db:
    rows = db.execute(select(StudioBusinessLink.servgo_business_id, Product.name)
                      .join(Product, Product.id == StudioBusinessLink.product_id)).all()
    total = db.scalar(select(func.count()).select_from(Product))
    canonical = db.scalars(select(Product).where(Product.slug == "servgo")).all()
    canonical_links = db.scalars(select(StudioBusinessLink).where(StudioBusinessLink.product_id.in_([p.id for p in canonical]))).all()
    print(json.dumps({"links": [[r[0], r[1]] for r in rows], "products": total,
                      "servgo_product_count": len(canonical), "servgo_link_count": len(canonical_links)}, ensure_ascii=False))
"""
    growth_mapping = {}
    growth_products = None
    servgo_product_info = {}
    try:
        checked = subprocess.run(
            ["docker", "exec", "ai-growth-os-api-1", "python", "-c", growth_code],
            capture_output=True, text=True, timeout=30, check=True,
        )
        info = json.loads(checked.stdout.strip().splitlines()[-1])
        growth_mapping = {int(key): name for key, name in info["links"]}
        growth_products = int(info["products"])
        servgo_product_info = {"products_named_servgo": info.get("servgo_product_count"), "linked_to_business": info.get("servgo_link_count")}
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError):
        # Missing Growth DB data is *not* a reason to merge users.
        pass
    result=[]
    for i,uid in enumerate(account_ids,1):
        u=user_data.get(uid)
        if u is None: continue
        result.append(dict(
            candidate=f"candidate_{i}",
            matches=sorted(signals[uid]),
            real_telegram_login=bool(u.telegram_id and u.telegram_id > 0),
            verified_email_login=(uid in all_email_users),
            yandex_identity=(uid in yandex_users),
            organisations=len(ownership[uid]),
            is_platform_owner_configured=((str(uid) == os.getenv("SERVGO_MAIL_OWNER_USER_ID") and bool(os.getenv("SERVGO_MAIL_OWNER_USER_ID"))) or (bool(os.getenv("SERVGO_MAIL_OWNER_TELEGRAM_ID")) and str(u.telegram_id) == os.getenv("SERVGO_MAIL_OWNER_TELEGRAM_ID"))),
            servgo_named_businesses_owned=sum(b.id in ownership[uid] for b in servgo_rows),
            growth_studio_links=sum(b in growth_mapping for b in ownership[uid]),
            growth_studio_names=sorted({growth_mapping[b] for b in ownership[uid] if b in growth_mapping})[:15],
            servgo_org_names=sorted({b.name for b in businesses if b.id in ownership[uid]})[:20],
            relevant_business_tags=sorted(tags[uid]),
            redirect_from_merges=sum(src==uid for src,_ in merges),
            redirect_to_merges=sum(dst==uid for _,dst in merges),
        ))
    unique_orgs=set().union(*(ownership[uid] for uid in account_ids)) if account_ids else set()
    print(json.dumps({
        "audit":"readonly",
        "candidates":result,
        "candidate_count":len(result),
        "total_distinct_businesses_for_candidates":len(unique_orgs),
        "servgo_named_businesses_in_booking_db":len(servgo_rows),
        "growth_existing_servgo":servgo_product_info,
        "growth_catalog_product_count": growth_products,
        "growth_links_total_count": len(growth_mapping),
        "verified_email_identity_candidate_count":len(verified_email_users),
        "yandex_identity_candidate_count":sum(uid in yandex_users for uid in account_ids),
        "merged_rows_within_candidates":sum(src in account_ids or dst in account_ids for src,dst in merges),
    }, ensure_ascii=False, sort_keys=True))
asyncio.run(run())
'''


def main():
    password = os.getenv("SERVGO_PASSWORD")
    if not password:
        raise RuntimeError("Production SSH access is not configured")
    encoded=base64.b64encode(REMOTE.encode()).decode()
    python_command = (
        "import base64;exec(compile(base64.b64decode("
        + repr(encoded) + "),'<servgo-readonly-identity-audit>','exec'))"
    )
    command = "cd " + shlex.quote(ROOT) + " && ./venv/bin/python -c " + shlex.quote(python_command)
    client=connect(password)
    try:
        _, stdout, stderr = client.exec_command(command, timeout=120)
        content=stdout.read().decode("utf-8","replace").strip()
        code=stdout.channel.recv_exit_status()
        if code:
            # Only emit the exception CLASS, never the underlying SQL query,
            # values or connection credentials.
            detail = stderr.read().decode("utf-8", "replace")
            for known in ("ModuleNotFoundError", "OperationalError", "ProgrammingError",
                          "UndefinedTableError", "AttributeError", "ImportError",
                          "SyntaxError", "TypeError", "InvalidPasswordError"):
                if known in detail:
                    print("readonly_audit_error_class=" + known)
                    break
            raise RuntimeError("Read-only identity audit failed (details hidden)")
        if not content.startswith("{") or '"audit": "readonly"' not in content:
            raise RuntimeError("Unexpected production audit result")
        print(content)
    finally:
        client.close()


if __name__=="__main__":
    main()
