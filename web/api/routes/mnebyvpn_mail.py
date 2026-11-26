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
from datetime import datetime, timedelta, timezone

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
    # Stream with a hard byte limit: request.body() would first buffer an
    # arbitrarily large unauthenticated payload in memory.
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > 512:
            raise HTTPException(413, "Request too large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
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
        if not isinstance(data, dict) or set(data) not in ({"email", "code"}, {"email", "kind", "expiresAt"}, {"email", "kind"}):
            raise ValueError("Bad payload")
        if not isinstance(data["email"], str):
            raise ValueError("Invalid recipient")
        email = normalize_optional_email(data["email"])
        if not email or email != str(data["email"]).lower().strip():
            raise ValueError("Bad email")
        if set(data) == {"email", "code"}:
            code = data["code"]
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                raise ValueError("Bad code")
            subject = "MNEBYVPN — код для входа"
            body = (
                f"Код для входа в MNEBYVPN: {code}\n"
                "Код действует 10 минут. Никому его не сообщайте.\n"
                "Если вы не запрашивали вход, просто игнорируйте письмо.\n"
            )
        elif set(data) == {"email", "kind"}:
            if data["kind"] not in ("vpn_trial_recovery_invite", "bundle_trial_recovery_invite"):
                raise ValueError("Bad trial invitation")
            subject = "MNEBYVPN — завершите получение бесплатного VPN"
            body = (
                "Если при оформлении пробного VPN произошла ошибка, теперь вы можете завершить оформление.\n"
                "Откройте личный кабинет с ранее подтверждённым email:\n"
                "https://mnebyvpn.site/#account\n\n"
                "Нажмите «Получить бесплатный VPN на 24 часа». Повторная регистрация не нужна.\n"
                "Пробный период начнётся только после активации. Если доступ не нужен, просто игнорируйте письмо.\n"
            )
            if data["kind"] == "bundle_trial_recovery_invite":
                subject = "MNEBYVPN — завершите получение бесплатного пакета «3 в 1»"
                body = (
                    "Если при оформлении бесплатного доступа произошла ошибка, откройте личный кабинет:\n"
                    "https://mnebyvpn.site/#account\n\n"
                    "Войдите с ранее подтверждённым email и нажмите «Попробовать 3 в 1 бесплатно».\n"
                    "VPN и Smart DNS предоставляются на 24 часа после активации. "
                    "Общий Telegram-прокси не ограничен пробными сутками.\n"
                    "Если доступ не нужен, просто игнорируйте письмо.\n"
                )
        else:
            if data["kind"] not in ("vpn_trial_ready", "bundle_trial_ready") or not isinstance(data["expiresAt"], str):
                raise ValueError("Bad trial notice")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", data["expiresAt"]):
                raise ValueError("Bad deadline")
            expires = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if not now < expires <= now + timedelta(hours=24, minutes=1):
                raise ValueError("Bad deadline")
            deadline = (expires.astimezone(timezone(timedelta(hours=3)))).strftime("%d.%m.%Y %H:%M")
            subject = "MNEBYVPN — бесплатный VPN готов"
            body = (
                "Ваш пробный VPN на 24 часа активирован.\n"
                f"Доступ действует до {deadline} (МСК).\n\n"
                "Откройте личный кабинет и выберите своё устройство:\n"
                "https://mnebyvpn.site/#account\n\n"
                "Если потребуется, войдите с помощью кода из письма.\n"
            )
            if data["kind"] == "bundle_trial_ready":
                subject = "MNEBYVPN — бесплатный пакет «3 в 1» готов"
                body = (
                    "Ваши VPN и Smart DNS активированы.\n"
                    f"Доступ действует до {deadline} (МСК).\n"
                    "Общий Telegram-прокси не ограничен пробными сутками.\n\n"
                    "Откройте личный кабинет, чтобы получить инструкции и подключения:\n"
                    "https://mnebyvpn.site/#account\n\n"
                    "При необходимости войдите с помощью кода из письма.\n"
                )
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid request") from None

    # Only ready notices may opt into stable delivery identity. The ordinary
    # OTP and invite replay contract is unchanged. A second durable marker is
    # bound to the exact signed payload; no schema change or recipient storage.
    stable_ready = (
        data.get("kind") in ("vpn_trial_ready", "bundle_trial_ready")
        and re.fullmatch(r"trial_[a-f0-9]{56}", nonce) is not None
    )
    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    success_digest = hashlib.sha256(b"sent:" + nonce.encode("ascii") + b":" + raw).hexdigest()
    db.add(MnebyvpnEmailDispatchNonce(nonce_hash=digest))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if stable_ready:
            accepted = await db.get(MnebyvpnEmailDispatchNonce, success_digest)
            if accepted is not None:
                return {"sent": True}
            # In-flight/crashed/ambiguous SMTP outcomes must not resend.
            raise HTTPException(409, "Delivery not confirmed") from None
        raise HTTPException(409, "Duplicate request") from None
    # Nonce cleanup is maintenance, not a prerequisite to mail delivery.
    # If the maintenance query fails, a valid signed code must still be sent.
    try:
        await db.execute(delete(MnebyvpnEmailDispatchNonce).where(
            MnebyvpnEmailDispatchNonce.created_at < utc_now() - timedelta(days=2)
        ))
        await db.commit()
    except Exception:
        await db.rollback()
    delivered = await send_email(
        to_email=email,
        subject=subject,
        text_body=body,
        from_override=_FROM,
    )
    if not delivered:
        raise HTTPException(503, "Email delivery unavailable")
    if stable_ready:
        db.add(MnebyvpnEmailDispatchNonce(nonce_hash=success_digest))
        await db.commit()
    return {"sent": True}
