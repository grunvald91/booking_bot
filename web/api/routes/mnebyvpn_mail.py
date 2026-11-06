"""Isolated MNEBYVPN OTP email delivery through ServGo's EXISTING SMTP setup.

This route does not authenticate a ServGo user and never exposes an SMTP secret.
Only the VPN backend may call it, with a dedicated HMAC secret provisioned on
both servers. A durable nonce rejects duplicate/replayed delivery requests.
"""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.email_notifications import email_channel_configured, send_email
from database.models import MnebyvpnEmailDispatchNonce
from datetime_utils import utc_now
from email_utils import normalize_optional_email
from ..database import get_db

router = APIRouter()
_FROM = "mnebyvpn@servgo.ru"
_NONCE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
_SIGNATURE = re.compile(r"^[a-f0-9]{64}$")
_CODE = re.compile(r"^\d{6}$")


def configured() -> bool:
    secret = os.getenv("MNEBYVPN_MAIL_GATEWAY_SECRET", "")
    return len(secret) >= 32 and email_channel_configured()


@router.post("/mnebyvpn/email-code")
async def send_mnebyvpn_code(request: Request, db: AsyncSession = Depends(get_db)):
    if not configured():
        raise HTTPException(503, "MNEBYVPN mail service is not configured")
    raw = await request.body()
    if len(raw) > 512 or not raw:
        raise HTTPException(400, "Invalid request")
    timestamp = request.headers.get("x-mnebyvpn-timestamp", "")
    nonce = request.headers.get("x-mnebyvpn-nonce", "")
    signature = request.headers.get("x-mnebyvpn-signature", "")
    if (not timestamp.isdigit() or len(timestamp) > 12 or
        abs(int(timestamp) - int(time.time())) > 60 or
        not _NONCE.fullmatch(nonce) or not _SIGNATURE.fullmatch(signature)):
        raise HTTPException(401, "Unauthorized")
    secret = os.environ["MNEBYVPN_MAIL_GATEWAY_SECRET"].encode()
    signed = timestamp.encode() + b"." + nonce.encode() + b"." + raw
    expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Unauthorized")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"email", "code"}:
            raise ValueError("Bad payload")
        if not isinstance(data["email"], str):
            raise ValueError("Invalid recipient")
        email = normalize_optional_email(data["email"])
        code = data["code"]
        if (not email or email != str(data["email"]).lower().strip()
                or not isinstance(code, str) or not _CODE.fullmatch(code)):
            raise ValueError("Bad email or code")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid request") from None

    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    db.add(MnebyvpnEmailDispatchNonce(nonce_hash=digest))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Duplicate request") from None
    # Best-effort cleanup ONLY this dedicated nonce table.
    await db.execute(delete(MnebyvpnEmailDispatchNonce).where(
        MnebyvpnEmailDispatchNonce.created_at < utc_now() - timedelta(days=2)
    ))
    await db.commit()
    delivered = await send_email(
        to_email=email,
        subject="MNEBYVPN — код для входа",
        text_body=(
            f"Код для входа в MNEBYVPN: {code}\n"
            "Код действует 10 минут. Никому его не сообщайте.\n"
            "Если вы не запрашивали вход, просто игнорируйте письмо.\n"
        ),
        from_override=_FROM,
    )
    if not delivered:
        raise HTTPException(503, "Email delivery unavailable")
    return {"sent": True}
