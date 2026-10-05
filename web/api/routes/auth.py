"""
Authentication routes.
Verification code is sent via Telegram bot. Fallback: server log.
"""
import os
import json
import random
import logging
import hmac
import hashlib
import httpx
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..database import get_db, User, Business, BusinessOwner
from ..deps import create_token, get_current_user
from ..schemas import (
    LoginPhoneIn,
    VerifyCodeIn,
    TelegramAuthIn,
    TokenOut,
    UserOut,
)
from servgo_auth import (
    auth_cookie_kwargs,
    auth_cookie_name,
    auth_dict_from_payload,
    create_or_update_user as shared_create_or_update_user,
    create_session as shared_create_session,
    get_session as shared_get_session,
    verify_telegram_login,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

logger = logging.getLogger(__name__)
router = APIRouter()


class TelegramLoginWidgetIn(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str

# In-memory verification codes: phone -> (code, timestamp)
_pending_codes: Dict[str, Tuple[str, float]] = {}
CODE_TTL_SECONDS = 300  # 5 minutes


def _normalize_phone(phone: str) -> str:
    """Strip spaces/dashes, ensure starts with +."""
    phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def _full_name_from_telegram(
    telegram_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    full_name = " ".join(
        part.strip()
        for part in (first_name or "", last_name or "")
        if part and part.strip()
    ).strip()
    return full_name or username or f"Telegram {telegram_id}"


async def _find_or_create_user_from_telegram(
    db: AsyncSession,
    telegram_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> User:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    full_name = _full_name_from_telegram(telegram_id, first_name, last_name, username)

    if user:
        changed = False
        if username is not None and user.username != username:
            user.username = username
            changed = True
        if full_name and full_name != f"Telegram {telegram_id}" and user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if changed:
            await db.commit()
            await db.refresh(user)
        return user

    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _role_for_user(db: AsyncSession, user: User) -> str:
    """Determine role from business ownership.
    Checks legacy Business.owner_id and BusinessOwner junction.
    """
    result = await db.execute(
        select(Business).where(Business.owner_id == user.id).limit(1)
    )
    if result.scalar_one_or_none():
        return "admin"

    owner_result = await db.execute(
        select(BusinessOwner).where(BusinessOwner.user_id == user.id).limit(1)
    )
    if owner_result.scalar_one_or_none():
        return "admin"

    return "client"


async def _token_for_telegram_user(
    db: AsyncSession,
    telegram_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> TokenOut:
    user = await _find_or_create_user_from_telegram(
        db,
        telegram_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )
    role = await _role_for_user(db, user)
    token = create_token(user.id, role=role)
    return TokenOut(
        token=token,
        user=UserOut.model_validate(user),
        role=role,
    )


# ---------- POST /auth/phone ----------

async def _send_code_via_telegram(phone: str, code: str, db: AsyncSession) -> bool:
    """Try to send verification code via Telegram bot. Returns True if sent."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not configured; Telegram OTP delivery is unavailable")
        return False
    try:
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if not user or not user.telegram_id or user.telegram_id < 0:
            return False
        text = f"🔐 Ваш код для входа на SochiService: <b>{code}</b>\n\nКод действителен 5 минут."
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "chat_id": user.telegram_id,
                "text": text,
                "parse_mode": "HTML",
            })
            return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception as e:
        logger.warning("Failed to send code via Telegram: %s", e)
        return False


@router.post("/phone")
async def request_code(body: LoginPhoneIn, db: AsyncSession = Depends(get_db)):
    """Generate a 6-digit code and send via Telegram bot."""
    import time as time_module
    phone = _normalize_phone(body.phone)
    code = f"{random.randint(100000, 999999)}"
    _pending_codes[phone] = (code, time_module.time())
    logger.warning("AUTH CODE for %s: %s", phone, code)

    sent = await _send_code_via_telegram(phone, code, db)
    if sent:
        return {"ok": True, "message": "Код отправлен в Telegram"}
    else:
        return {"ok": True, "message": "Код отправлен (проверьте Telegram)", "fallback": True}


# ---------- POST /auth/verify ----------

@router.post("/verify", response_model=TokenOut)
async def verify_code(
    body: VerifyCodeIn,
    db: AsyncSession = Depends(get_db),
):
    """Verify the code, find-or-create user, return JWT with role from ownership."""
    import time as time_module
    phone = _normalize_phone(body.phone)
    entry = _pending_codes.get(phone)

    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    expected_code, created_at = entry
    if time_module.time() - created_at > CODE_TTL_SECONDS:
        _pending_codes.pop(phone, None)
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")

    if expected_code != body.code:
        raise HTTPException(status_code=400, detail="Invalid code")

    # Code used — remove it
    _pending_codes.pop(phone, None)

    # Find user by phone
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=-int(time_module.time() * 1000) % 2_000_000_000,
            full_name=phone,
            phone=phone,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    role = await _role_for_user(db, user)
    token = create_token(user.id, role=role)
    return TokenOut(
        token=token,
        user=UserOut.model_validate(user),
        role=role,
    )


# ---------- POST /auth/telegram ----------

def _validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp initData and return user dict if valid."""
    try:
        parsed = parse_qs(init_data)
        data_check = {}
        for k, v in parsed.items():
            data_check[k] = v[0]

        check_hash = data_check.pop("hash", None)
        if not check_hash:
            return None

        sorted_items = sorted(data_check.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if computed != check_hash:
            logger.warning("initData hash mismatch")
            return None

        user_json = data_check.get("user")
        if user_json:
            return json.loads(user_json)
        return None
    except Exception as e:
        logger.warning("Failed to validate initData: %s", e)
        return None


def _shared_auth_from_init_data(init_data: str, tg_user: dict) -> Optional[dict]:
    parsed = parse_qs(init_data)
    flat = {key: value[0] for key, value in parsed.items() if value}
    if not flat.get("hash") or not flat.get("auth_date"):
        return None

    return auth_dict_from_payload(
        {
            "id": tg_user.get("id"),
            "first_name": tg_user.get("first_name"),
            "last_name": tg_user.get("last_name"),
            "username": tg_user.get("username"),
            "photo_url": tg_user.get("photo_url"),
            "auth_date": flat.get("auth_date"),
            "hash": flat.get("hash"),
        }
    )


async def _set_shared_auth_cookie(response: Response, auth_dict: dict) -> None:
    await run_in_threadpool(lambda: shared_create_or_update_user(auth_dict))
    shared_token = await run_in_threadpool(
        lambda: shared_create_session(int(auth_dict["id"]), source_service="booking")
    )
    response.set_cookie(auth_cookie_name(), shared_token, **auth_cookie_kwargs())


@router.post("/telegram-login", response_model=TokenOut)
async def telegram_login_widget(
    body: TelegramLoginWidgetIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate via Telegram Login Widget and issue both JWT and shared cookie."""
    auth_payload = body.model_dump(exclude_none=True)
    if not verify_telegram_login(auth_payload, [BOT_TOKEN]):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth payload")

    shared_auth = auth_dict_from_payload(auth_payload)
    token_out = await _token_for_telegram_user(
        db,
        int(shared_auth["id"]),
        first_name=shared_auth.get("first_name"),
        last_name=shared_auth.get("last_name"),
        username=shared_auth.get("username"),
    )
    await _set_shared_auth_cookie(response, shared_auth)
    return token_out


@router.get("/session", response_model=TokenOut)
async def session_from_shared_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid shared auth cookie for this SPA's JWT."""
    raw_token = request.cookies.get(auth_cookie_name())
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    shared_session = await run_in_threadpool(lambda: shared_get_session(raw_token))
    if not shared_session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return await _token_for_telegram_user(
        db,
        int(shared_session["telegram_id"]),
        first_name=shared_session.get("first_name"),
        last_name=shared_session.get("last_name"),
        username=shared_session.get("username"),
    )


@router.post("/telegram", response_model=TokenOut)
async def telegram_auth(
    body: TelegramAuthIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate via Telegram WebApp initData. Auto-creates user if needed."""
    tg_user = _validate_init_data(body.init_data)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="No user id in initData")

    token_out = await _token_for_telegram_user(
        db,
        int(telegram_id),
        first_name=tg_user.get("first_name"),
        last_name=tg_user.get("last_name"),
        username=tg_user.get("username"),
    )
    shared_auth = _shared_auth_from_init_data(body.init_data, tg_user)
    if shared_auth:
        await _set_shared_auth_cookie(response, shared_auth)
    return token_out


# ---------- GET /auth/me ----------

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return UserOut.model_validate(user)
