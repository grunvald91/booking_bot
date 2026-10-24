"""Sign in with Yandex ID.

Flow: /yandex/start -> Yandex -> /yandex/callback (server side: code, token, profile) -> a one-time
ticket -> the web page calls /yandex/exchange. A Yandex phone that matches an existing Telegram
account is joined to it only after the owner of that Telegram enters a code the bot sent there.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datetime_utils import utc_now
from database.models import User, YandexIdentity, YandexTicket
from email_utils import normalize_optional_email
from .. import deps
from ..database import get_db
from ..photo_transport import create_photo_client
from ..schemas import TokenOut, UserOut
from .auth import _normalize_phone, _role_for_user, _user_by_phone

logger = logging.getLogger(__name__)
router = APIRouter()

AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"
INFO_URL = "https://login.yandex.ru/info"
COOKIE = "servgo_yx"
FLOW_MINUTES = 10
CODE_MINUTES = 5
MAX_ATTEMPTS = 5
MAX_SENDS = 3
RESEND_SECONDS = 60


def client_id() -> str:
    return os.getenv("YANDEX_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.getenv("YANDEX_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.getenv("YANDEX_REDIRECT_URI", "https://servgo.ru/api/auth/yandex/callback").strip()


def configured() -> bool:
    return bool(client_id() and client_secret() and len(deps.SECRET_KEY) >= 32)


def _mac(value: str) -> str:
    return hmac.new(("yandex-login:" + deps.SECRET_KEY).encode(), value.encode(), hashlib.sha256).hexdigest()


def _seal(data: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    return body + "." + _mac(body)


def _unseal(cookie: Optional[str]) -> Optional[dict]:
    if not cookie or "." not in cookie:
        return None
    body, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _mac(body)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("exp", 0) > utc_now().timestamp() else None


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def _authorize_url(state: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code", "client_id": client_id(), "redirect_uri": redirect_uri(),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })


def _start_flow(response: Response, link_user_id: Optional[int]) -> str:
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    response.set_cookie(
        COOKIE, _seal({"s": state, "v": verifier, "u": link_user_id, "exp": int(utc_now().timestamp()) + FLOW_MINUTES * 60}),
        max_age=FLOW_MINUTES * 60, httponly=True, secure=True, samesite="lax", path="/api/auth/yandex",
    )
    return _authorize_url(state, verifier)


def parse_birthday(raw) -> Optional[str]:
    """Yandex gives YYYY-MM-DD, with 0000 when the year is unknown. Month and day are required."""
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    _, month, day = (int(part) for part in raw.split("-"))
    return raw if 1 <= month <= 12 and 1 <= day <= 31 else None


def profile_from(info: dict) -> dict:
    phone = (info.get("default_phone") or {}).get("number") if isinstance(info.get("default_phone"), dict) else None
    first, last = (info.get("first_name") or "").strip(), (info.get("last_name") or "").strip()
    name = (info.get("real_name") or " ".join(part for part in (first, last) if part)).strip() \
        or (info.get("display_name") or "").strip() or (info.get("login") or "").strip()
    email = None
    try:
        email = normalize_optional_email(info.get("default_email") or "")
    except Exception:
        email = None
    normalized_phone = None
    if isinstance(phone, str) and re.fullmatch(r"\+?\d{10,15}", re.sub(r"[\s()\-]", "", phone)):
        normalized_phone = _normalize_phone(phone)[:20]
    return {"id": str(info["id"])[:32], "login": (info.get("login") or "")[:255], "name": (name or "Яндекс")[:255],
            "email": email, "phone": normalized_phone, "birthday": parse_birthday(info.get("birthday"))}


async def fetch_profile(code: str, verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False) as http:
        token = await http.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "client_id": client_id(),
            "client_secret": client_secret(), "code_verifier": verifier,
        })
        token.raise_for_status()
        access = token.json()["access_token"]
        info = await http.get(INFO_URL, params={"format": "json"}, headers={"Authorization": "OAuth " + access})
        info.raise_for_status()
        return profile_from(info.json())


def _back(path: str) -> RedirectResponse:
    redirect = RedirectResponse(path, status_code=302)
    redirect.delete_cookie(COOKIE, path="/api/auth/yandex")
    redirect.headers["Cache-Control"] = "no-store"
    redirect.headers["Referrer-Policy"] = "no-referrer"
    return redirect


@router.get("/yandex/capabilities")
async def capabilities():
    return {"available": configured()}


@router.get("/yandex/start")
async def start():
    if not configured():
        return RedirectResponse("/login?yandex=unavailable", status_code=302)
    redirect = RedirectResponse("/", status_code=302)
    redirect.headers["Location"] = _start_flow(redirect, None)
    redirect.headers["Cache-Control"] = "no-store"
    return redirect


@router.post("/yandex/link/start")
async def link_start(response: Response, user: User = Depends(deps.get_current_user)):
    if not configured():
        raise HTTPException(503, "Вход через Яндекс пока не настроен")
    return {"url": _start_flow(response, user.id)}


@router.get("/yandex/account")
async def account(user: User = Depends(deps.get_current_user), db: AsyncSession = Depends(get_db)):
    identity = await db.scalar(select(YandexIdentity).where(YandexIdentity.user_id == user.id))
    return {"available": configured(), "linked": identity is not None, "login": identity.login if identity else None}


@router.get("/yandex/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", db: AsyncSession = Depends(get_db)):
    flow = _unseal(request.cookies.get(COOKIE))
    if not configured() or not flow or not state or not hmac.compare_digest(str(flow.get("s", "")), state):
        return _back("/login?yandex=expired")
    link = flow.get("u") is not None
    if error or not code:
        return _back("/login?yandex=denied")
    try:
        profile = await fetch_profile(code, flow["v"])
    except Exception as exc:
        # Never log the exception text: it can carry request details.
        logger.warning("yandex_login_failed: %s", type(exc).__name__)
        return _back("/login?yandex=failed")
    await db.execute(delete(YandexTicket).where(YandexTicket.expires_at < utc_now()))
    ticket = secrets.token_urlsafe(32)
    db.add(YandexTicket(id=_ticket_hash(ticket), payload=json.dumps(profile, ensure_ascii=False),
                        link_user_id=flow.get("u"), expires_at=utc_now() + timedelta(minutes=FLOW_MINUTES)))
    await db.commit()
    # The secret travels in the URL fragment: it is not sent to servers or written to their logs.
    return _back("/login/yandex#ticket=" + ticket)


class ExchangeIn(BaseModel):
    ticket: str = Field(min_length=20, max_length=80)
    code: Optional[str] = Field(default=None, pattern=r"^\d{6}$")
    separate: bool = False


async def _issue(db: AsyncSession, user: User) -> dict:
    role = await _role_for_user(db, user)
    out = TokenOut(token=deps.create_token(user.id, role=role), user=UserOut.model_validate(user), role=role)
    return {"status": "ok", **out.model_dump()}


def _fill_missing(user: User, profile: dict, *, phone: bool = True) -> None:
    """Add what the account lacks; never overwrite what the person already has."""
    if profile.get("birthday") and not user.birthday:
        user.birthday = profile["birthday"]
    if profile.get("email") and not user.email:
        user.email = profile["email"]
    if phone and profile.get("phone") and not user.phone:
        user.phone = profile["phone"]


async def _send_code(target: User, code: str) -> bool:
    if not os.getenv("BOT_TOKEN") or not target.telegram_id or target.telegram_id < 0:
        return False
    text = (f"🔐 Код для входа в ServGo через Яндекс: <b>{code}</b>\n\nКод действует {CODE_MINUTES} минут. "
            "Если вы его не запрашивали, ничего не делайте.")
    try:
        async with create_photo_client() as http:
            response = await http.post(f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage",
                                       json={"chat_id": target.telegram_id, "text": text, "parse_mode": "HTML"})
            return response.status_code == 200 and response.json().get("ok", False)
    except Exception as exc:
        logger.warning("yandex_code_send_failed: %s", type(exc).__name__)
        return False


async def _consume(ticket: YandexTicket) -> None:
    ticket.consumed = True


@router.post("/yandex/exchange")
async def exchange(body: ExchangeIn, user: Optional[User] = Depends(deps.get_current_user_optional),
                   db: AsyncSession = Depends(get_db)):
    ticket = await db.scalar(select(YandexTicket).where(YandexTicket.id == _ticket_hash(body.ticket)).with_for_update())
    now = utc_now()
    if ticket is None or ticket.consumed or ticket.expires_at <= now:
        raise HTTPException(400, "Ссылка входа устарела. Нажмите «Войти через Яндекс» ещё раз")
    profile = json.loads(ticket.payload)
    existing = await db.scalar(select(YandexIdentity).where(YandexIdentity.yandex_id == profile["id"]))

    # --- attach Yandex to the account that is already signed in
    if ticket.link_user_id is not None:
        if user is None or user.id != ticket.link_user_id:
            raise HTTPException(401, "Войдите в аккаунт и повторите привязку")
        if existing is not None:
            raise HTTPException(409, "Этот Яндекс-аккаунт уже привязан к другому аккаунту ServGo" if existing.user_id != user.id
                                else "Этот Яндекс уже привязан к вашему аккаунту")
        if await db.scalar(select(YandexIdentity).where(YandexIdentity.user_id == user.id)):
            raise HTTPException(409, "К вашему аккаунту уже привязан другой Яндекс")
        db.add(YandexIdentity(yandex_id=profile["id"], user_id=user.id, login=profile["login"]))
        _fill_missing(user, profile)
        await _consume(ticket)
        await db.commit()
        return {"status": "linked"}

    # --- the Yandex account is already known: sign in
    if existing is not None:
        target = await db.get(User, existing.user_id)
        if target is None:
            raise HTTPException(400, "Аккаунт не найден")
        _fill_missing(target, profile, phone=False)
        await _consume(ticket)
        await db.commit()
        return await _issue(db, target)

    # --- a Telegram account with the same phone: join only after a code from that Telegram
    match = None
    if profile.get("phone") and not body.separate:
        candidate = await _user_by_phone(db, profile["phone"])
        if candidate is not None and candidate.telegram_id and candidate.telegram_id > 0 \
                and not await db.scalar(select(YandexIdentity).where(YandexIdentity.user_id == candidate.id)):
            match = candidate
    if match is not None:
        if body.code:
            if ticket.attempts >= MAX_ATTEMPTS:
                await _consume(ticket); await db.commit()
                raise HTTPException(400, "Слишком много неверных кодов. Начните вход заново")
            ok = (ticket.code_hash and ticket.code_user_id == match.id and ticket.code_sent_at
                  and ticket.code_sent_at + timedelta(minutes=CODE_MINUTES) > now
                  and hmac.compare_digest(ticket.code_hash, _mac(ticket.id + body.code)))
            if not ok:
                ticket.attempts += 1
                await db.commit()
                raise HTTPException(400, "Неверный или просроченный код")
            db.add(YandexIdentity(yandex_id=profile["id"], user_id=match.id, login=profile["login"]))
            _fill_missing(match, profile, phone=False)
            await _consume(ticket)
            await db.commit()
            return await _issue(db, match)
        recently = ticket.code_sent_at and ticket.code_sent_at + timedelta(seconds=RESEND_SECONDS) > now
        if recently or ticket.sends >= MAX_SENDS:
            return {"status": "code_required"}
        code = f"{secrets.randbelow(900000) + 100000}"
        sent = await _send_code(match, code)
        if not sent:
            return {"status": "code_unavailable"}
        ticket.code_hash, ticket.code_user_id, ticket.code_sent_at = _mac(ticket.id + code), match.id, now
        ticket.sends += 1
        await db.commit()
        return {"status": "code_required"}

    # --- a new person (or one who chose a separate account)
    phone_taken = bool(profile.get("phone")) and await _user_by_phone(db, profile["phone"]) is not None
    new_user = User(telegram_id=-secrets.randbelow(2**62 - 1) - 1, full_name=profile["name"],
                    email=profile.get("email"), phone=None if phone_taken else profile.get("phone"),
                    birthday=profile.get("birthday"))
    db.add(new_user)
    await db.flush()
    db.add(YandexIdentity(yandex_id=profile["id"], user_id=new_user.id, login=profile["login"]))
    await _consume(ticket)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Вход уже выполняется. Нажмите «Войти через Яндекс» ещё раз") from None
    return await _issue(db, new_user)
