"""One-time guarded creation of the ServGo *platform organisation*.

Precondition: production read-only audit proved one existing Growth product
slug='servgo' (unlinked), and no BookingBot business named ServGo.

Only a verified user with the owner's actual linked email, Telegram and Yandex
identities can receive the organisation. The Growth product is reused, never
cloned. A generated BookingBot platform organisation is inactive for public
booking by design.

Run under GitHub Actions with APPLY=false first. Run with APPLY=true only when
the preflight was successful. The two independent databases cannot participate
in a distributed transaction; compensating rollback is limited to the new,
unmodified business if Growth linking fails. Never log raw owner identifiers,
email addresses, phone numbers, secrets, or organisation primary keys.
"""

from __future__ import annotations

import base64
import json
import os
import shlex

from scripts.deploy_business_creation_and_reminders import ROOT, connect

# Hash of the email explicitly verified by the owner's previous ServGo audit.
EMAIL_SHA256 = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"
TELEGRAM_USERNAME = "grunvald"
PHONE_SUFFIX = "1399"

_BOOKING = r'''
import asyncio, hashlib, json, os, sys
from sqlalchemy import select, func, delete
from dotenv import load_dotenv
load_dotenv("/opt/booking_bot/.env")
from bot.config import DATABASE_URL as BOT_DATABASE_URL
os.environ.setdefault("DATABASE_URL", BOT_DATABASE_URL)
from web.api.database import async_session
from database.models import User, EmailIdentity, YandexIdentity, Business, BusinessOwner, Service, Employee

EMAIL_SHA256 = "d249e49897ff0e3fc98cb09ce02bf1edb23b620fbef571931f9fd0e8730e36af"
ACTION = sys.argv[1]
KEY = int(sys.argv[2]) if len(sys.argv) > 2 else None

def is_owner(user, email_id, yandex_id):
    return (email_id is not None and email_id.user_id == user.id and
            hashlib.sha256(email_id.email.strip().lower().encode()).hexdigest() == EMAIL_SHA256 and
            yandex_id is not None and yandex_id.user_id == user.id and
            user.telegram_id is not None and user.telegram_id > 0 and
            (user.username or "").lstrip("@").casefold() == "grunvald" and
            (user.phone or "").replace(" ", "").endswith("1399"))

async def main():
    async with async_session() as db:
        emails = list((await db.scalars(select(EmailIdentity))).all())
        verified = [e for e in emails if hashlib.sha256(e.email.strip().lower().encode()).hexdigest() == EMAIL_SHA256]
        if len(verified) != 1:
            raise RuntimeError("Expected exactly one verified owner email identity")
        user = await db.get(User, verified[0].user_id, with_for_update=True)
        yandex = await db.scalar(select(YandexIdentity).where(YandexIdentity.user_id == user.id))
        if not is_owner(user, verified[0], yandex):
            raise RuntimeError("Owner provider identities differ; refuse provisioning")
        # No platform organisation may already belong to someone else.
        existing = list((await db.scalars(select(Business).where(func.lower(Business.name) == "servgo"))).all())
        if len(existing) > 1:
            raise RuntimeError("Multiple platform organisations; refuse")
        business = existing[0] if existing else None
        if business and (business.owner_id != user.id or business.is_active or business.business_type != "platform"):
            raise RuntimeError("Existing ServGo organisation belongs to another user or is not a platform record")
        if ACTION == "check":
            print(json.dumps({"ok":True,"state":"existing" if business else "new",
                "business_id":business.id if business else None}))
            return
        if ACTION == "create":
            if business is None:
                business = Business(owner_id=user.id, name="ServGo", business_type="platform",
                    description="Платформа ServGo", is_active=False)
                db.add(business)
                await db.flush()
            result = business.id
            await db.commit()
            print(json.dumps({"ok":True,"business_id":result}))
            return
        if ACTION == "rollback":
            if business is None:
                print(json.dumps({"ok":True,"state":"already-absent"}))
                return
            if business.id != KEY:
                raise RuntimeError("Rollback business ID differs")
            for model in (BusinessOwner, Service, Employee):
                if await db.scalar(select(model.id).where(model.business_id == business.id).limit(1)):
                    raise RuntimeError("Rollback business has dependents, leave it for manual review")
            await db.delete(business)
            await db.commit()
            print(json.dumps({"ok":True,"state":"rolled-back"}))
            return
        raise RuntimeError("Unknown action")
asyncio.run(main())
'''

_GROWTH = r'''
import json, sys
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.domain import Product
from app.sso.models import StudioBusinessLink

ACTION = sys.argv[1]
BUSINESS_ID = int(sys.argv[2]) if len(sys.argv) > 2 else None
with SessionLocal() as db:
    products = list(db.scalars(select(Product).where(Product.slug == "servgo")))
    if len(products) != 1 or (products[0].name or "").strip().casefold() != "servgo":
        raise RuntimeError("Existing platform Growth product is not unique and verified")
    product = products[0]
    links = list(db.scalars(select(StudioBusinessLink).where(StudioBusinessLink.product_id == product.id)))
    if len(links) > 1:
        raise RuntimeError("Platform product has multiple links")
    existing = links[0] if links else None
    if ACTION == "check":
        print(json.dumps({"ok":True,"linked":bool(existing),
                          "business_id":existing.servgo_business_id if existing else None}))
    elif ACTION == "link":
        if BUSINESS_ID is None or BUSINESS_ID < 1:
            raise RuntimeError("Invalid business ID")
        if existing is not None and existing.servgo_business_id != BUSINESS_ID:
            raise RuntimeError("Platform project already belongs to a different ServGo business")
        other = db.scalar(select(StudioBusinessLink).where(
            StudioBusinessLink.servgo_business_id == BUSINESS_ID))
        if other is not None and other.product_id != product.id:
            raise RuntimeError("ServGo business already linked to a different Growth product")
        if existing is None and other is None:
            db.add(StudioBusinessLink(servgo_business_id=BUSINESS_ID, product_id=product.id))
            db.commit()
        print(json.dumps({"ok":True,"linked":True}))
    else:
        raise RuntimeError("Unknown action")
'''


def run_script(client, script: str, args: list[str], *, docker: bool = False) -> dict:
    """Run a fixed internal script and return only allowlisted control fields."""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    py = "import base64;exec(compile(base64.b64decode(" + repr(encoded) + "),'<servgo-provision>','exec'))"
    cmd = ("docker exec ai-growth-os-api-1 python -c " if docker else
           f"cd {shlex.quote(ROOT)} && ./venv/bin/python -c ")
    cmd += shlex.quote(py) + "".join(" " + shlex.quote(arg) for arg in args)
    _, stdout, _ = client.exec_command(cmd, timeout=100)
    result = stdout.read().decode("utf-8","replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError("Provisioning script failed safely on " + ("Growth" if docker else "ServGo"))
    try:
        message = json.loads(result.strip().splitlines()[-1])
        if message.get("ok") is not True:
            raise ValueError("not ok")
        return message
    except (IndexError, ValueError, TypeError) as exc:
        raise RuntimeError("Unexpected provisioning response") from exc


def main() -> None:
    password = os.environ.get("SERVGO_PASSWORD", "")
    if not password:
        raise RuntimeError("SSH credentials unavailable")
    apply = os.environ.get("APPLY", "").lower() == "true"
    client = connect(password)
    created_id = None
    try:
        booking = run_script(client, _BOOKING, ["check"])
        growth = run_script(client, _GROWTH, ["check"], docker=True)
        if growth["linked"] and booking["business_id"] != growth["business_id"]:
            raise RuntimeError("Platform Growth product is already mapped differently")
        if booking["business_id"] is not None and not growth["linked"]:
            # This may be a partial previous apply. It is safe only if the
            # booking record already satisfies all platform-owner constraints.
            pass
        if not apply:
            print(json.dumps({
                "provision_preflight_ok": True,
                "booking_business_exists": booking["business_id"] is not None,
                "growth_product_already_linked": bool(growth["linked"]),
                "production_untouched": True,
            }))
            return
        if booking["business_id"] is None:
            new = run_script(client, _BOOKING, ["create"])
            created_id = new["business_id"]
            business_id = created_id
        else:
            business_id = booking["business_id"]
        try:
            run_script(client, _GROWTH, ["link", str(business_id)], docker=True)
        except Exception:
            # If the Growth command committed but network failed, do not delete
            # a business still referenced by the Growth DB.
            latest = run_script(client, _GROWTH, ["check"], docker=True)
            if created_id is not None and not latest["linked"]:
                run_script(client, _BOOKING, ["rollback", str(created_id)])
                print("platform_business_compensating_rollback=ok")
            raise
        print(json.dumps({
            "platform_business_exists": True,
            "growth_product_reused": True,
            "platform_product_linked": True,
            "created_new_business": created_id is not None,
            "public_bookings_disabled": True,
        }))
    finally:
        client.close()


if __name__ == "__main__":
    main()
