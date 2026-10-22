"""Single sign-on between the ServGo admin and the marketing studio (growth.servgo.ru).

Two small, independent pieces:

* ``POST /studio/ticket`` — a signed-in person asks for a link into the studio. The answer is a
  one-time link that lives 60 seconds. The studio exchanges it for its own sign-in.
* ``GET /internal/studio/access`` — the studio asks, with a private key, whether this person
  still has access to this business *right now*. Removing someone here cuts the studio access too.

Nothing here lets the studio read bookings, clients or money. It only answers yes/no and a role.
Both pieces refuse to work (503) until the secrets are set in the environment.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Business, BusinessOwner, Employee, User, get_db
from ..deps import get_current_user

router = APIRouter()

TICKET_TTL_SECONDS = 60
AUDIENCE = "growth-studio"
MIN_SECRET_LENGTH = 32
STUDIO_URL = "https://growth.servgo.ru"


def _secret(name: str) -> bytes:
    value = os.getenv(name, "")
    if len(value) < MIN_SECRET_LENGTH:
        raise HTTPException(status_code=503, detail="Studio sign-in is not configured")
    return value.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_ticket(*, user_id: int, business_id: int, role: str, name: str, now: Optional[float] = None) -> str:
    payload = _b64(json.dumps({
        "v": 1, "aud": AUDIENCE, "uid": user_id, "biz": business_id, "role": role, "name": name[:120],
        "jti": secrets.token_urlsafe(16), "exp": int((now if now is not None else time.time()) + TICKET_TTL_SECONDS),
    }, separators=(",", ":"), ensure_ascii=False).encode())
    signature = _b64(hmac.new(_secret("STUDIO_SSO_SECRET"), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


async def studio_role(db: AsyncSession, user_id: int, business_id: int) -> Optional[str]:
    """Role this person has in the studio for this business, or None when they have no access."""
    business = await db.get(Business, business_id)
    if business is None:
        return None
    if business.owner_id == user_id:
        return "owner"
    link = await db.scalar(select(BusinessOwner).where(
        BusinessOwner.business_id == business_id, BusinessOwner.user_id == user_id))
    if link is not None:
        return link.role if link.role in ("owner", "co_owner") else "co_owner"
    if not business.studio_admin_access:
        return None
    user = await db.get(User, user_id)
    if user is None or not user.telegram_id:
        return None
    admin = await db.scalar(select(Employee).where(
        Employee.business_id == business_id, Employee.telegram_id == user.telegram_id,
        Employee.role == "administrator", Employee.is_active.is_(True)))
    return "administrator" if admin is not None else None


class TicketIn(BaseModel):
    business_id: int


class TicketOut(BaseModel):
    url: str
    expires_in: int = TICKET_TTL_SECONDS


@router.post("/studio/ticket", response_model=TicketOut)
async def studio_ticket(data: TicketIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """One-time link into the studio for a business the person is allowed to manage."""
    role = await studio_role(db, user.id, data.business_id)
    if role is None:
        raise HTTPException(status_code=403, detail="No access to the marketing studio for this business")
    business = await db.get(Business, data.business_id)
    ticket = make_ticket(user_id=user.id, business_id=business.id, role=role, name=business.name or "")
    return TicketOut(url=f"{STUDIO_URL}/studio/sso?t={ticket}")


class AccessOut(BaseModel):
    allowed: bool
    role: Optional[str] = None


@router.get("/internal/studio/access", response_model=AccessOut)
async def studio_access(user_id: int, business_id: int, x_studio_key: str = Header(default=""),
                        db: AsyncSession = Depends(get_db)):
    """Server-to-server check used by the studio on every request. Answers only yes/no and a role."""
    expected = _secret("STUDIO_INTERNAL_KEY")
    if not hmac.compare_digest(x_studio_key.encode(), expected):
        raise HTTPException(status_code=403, detail="Forbidden")
    role = await studio_role(db, user_id, business_id)
    return AccessOut(allowed=role is not None, role=role)
