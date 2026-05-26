"""
AI chat route — real implementation with OpenRouter API.
Handles client AI flow: browse, book, cancel, reschedule.
"""
import os
import json
import logging
import uuid
import datetime
from typing import Optional

import hmac
import hashlib
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db, Business, Service, Employee, Booking, User, VenueTimePricing
from ..deps import get_current_user, get_current_user_optional
from ..schemas import AIChatIn, AIChatOut, AIConfirmIn

BOT_TOKEN = os.getenv("BOT_TOKEN", "***REMOVED***")

# Import EmployeeService directly from models (not re-exported by web database)
from database.models import EmployeeService

router = APIRouter()
logger = logging.getLogger(__name__)


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

        # Create data-check-string
        sorted_items = sorted(data_check.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

        # HMAC-SHA256 with WebAppData key
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


async def _get_ai_user(
    request: Request,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get user from JWT token or Telegram initData header."""
    # Try JWT first
    if authorization and authorization.startswith("Bearer "):
        from ..deps import get_current_user as _get_user
        try:
            return await _get_user(authorization=authorization, db=db)
        except HTTPException:
            pass

    # Try Telegram initData from header
    tg_init_data = request.headers.get("X-Telegram-Init-Data", "")
    if tg_init_data:
        tg_user = _validate_init_data(tg_init_data)
        if tg_user and tg_user.get("id"):
            tg_id = tg_user["id"]
            result = await db.execute(select(User).where(User.telegram_id == tg_id))
            user = result.scalar_one_or_none()
            if user:
                return user
            # Create user from Telegram data
            name_parts = [tg_user.get("first_name", "")]
            if tg_user.get("last_name"):
                name_parts.append(tg_user["last_name"])
            user = User(
                telegram_id=tg_id,
                full_name=" ".join(name_parts),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    # Guest fallback — allow AI chat without login (read-only, no mutations)
    import time as time_module
    guest_tg_id = -int(time_module.time() * 1000) % 2_000_000_000
    # Try to find existing guest by IP-based cookie or create new
    user = User(telegram_id=guest_tg_id, full_name="Гость")
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except Exception:
        await db.rollback()
        # On collision, generate a different ID
        guest_tg_id = -int(time_module.time() * 1000000) % 2_000_000_000
        user = User(telegram_id=guest_tg_id, full_name="Гость")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

# ─── OpenRouter config ────────────────────────────────────────────────────────

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.getenv(
    "OPENROUTER_AI_ADMIN_KEY",
    "***REMOVED***",
)
MODELS = [
    "qwen/qwen3-235b-a22b-2507",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-120b",
]
TEMPERATURE = 0.3
MAX_LOOPS = 6  # max agentic tool iterations per request

# ─── In-memory state ──────────────────────────────────────────────────────────

# Conversation history per user_id
_histories: dict[int, list[dict]] = {}
MAX_HISTORY = 30  # keep last N messages per user

# Pending mutation actions awaiting user confirmation
_pending: dict[str, dict] = {}

# ─── Tool schemas (from client_admin_tools.py) ────────────────────────────────

CLIENT_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_additional_services",
        "description": "Show additional services for a venue (venue_rental only). Call after selecting the main service.",
        "parameters": {"type": "object",
                       "properties": {"business_id": {"type": "integer"}},
                       "required": ["business_id"]}}},
    {"type": "function", "function": {
        "name": "get_available_slots",
        "description": "Get available booking slots for a date",
        "parameters": {"type": "object",
                       "properties": {
                           "business_id":  {"type": "integer"},
                           "service_id":   {"type": "integer"},
                           "date":         {"type": "string", "description": "YYYY-MM-DD"},
                           "employee_id":  {"type": "integer", "description": "Optional: specific employee/venue"}},
                       "required": ["business_id", "service_id", "date"]}}},
    {"type": "function", "function": {
        "name": "get_my_bookings",
        "description": "Show client's bookings",
        "parameters": {"type": "object",
                       "properties": {
                           "status": {"type": "string",
                                      "enum": ["upcoming", "all", "cancelled"],
                                      "description": "Status filter. Default: upcoming."}}}}},
    {"type": "function", "function": {
        "name": "create_booking",
        "description": "Create a booking for the client.",
        "parameters": {"type": "object",
                       "properties": {
                           "business_id":           {"type": "integer"},
                           "service_id":            {"type": "integer"},
                           "date":                  {"type": "string", "description": "YYYY-MM-DD"},
                           "time":                  {"type": "string", "description": "HH:MM"},
                           "employee_id":           {"type": "integer"},
                           "additional_service_ids":{"type": "array", "items": {"type": "integer"}},
                           "notes":                 {"type": "string"},
                           "business_name":         {"type": "string"},
                           "service_name":          {"type": "string"}},
                       "required": ["business_id", "service_id", "date", "time"]}}},
    {"type": "function", "function": {
        "name": "confirm_payment_sent",
        "description": "Client confirms they sent prepayment.",
        "parameters": {"type": "object",
                       "properties": {"booking_id": {"type": "integer"}},
                       "required": ["booking_id"]}}},
    {"type": "function", "function": {
        "name": "cancel_my_booking",
        "description": "Cancel client's own booking",
        "parameters": {"type": "object",
                       "properties": {
                           "booking_id": {"type": "integer"},
                           "reason":     {"type": "string"}},
                       "required": ["booking_id"]}}},
    {"type": "function", "function": {
        "name": "reschedule_my_booking",
        "description": "Reschedule client's own booking to a different date/time",
        "parameters": {"type": "object",
                       "properties": {
                           "booking_id": {"type": "integer"},
                           "new_date":   {"type": "string", "description": "YYYY-MM-DD"},
                           "new_time":   {"type": "string", "description": "HH:MM"}},
                       "required": ["booking_id", "new_date", "new_time"]}}},
]

READ_ONLY_TOOLS = {"get_additional_services", "get_available_slots", "get_my_bookings"}
MUTATION_TOOLS = {"create_booking", "confirm_payment_sent", "cancel_my_booking", "reschedule_my_booking"}

# Human-readable descriptions for mutation confirmation
MUTATION_DESCRIPTIONS = {
    "create_booking": lambda a: (
        f"Записать вас: {a.get('business_name', 'Заведение')} - "
        f"{a.get('service_name', 'Услуга')}, "
        f"{a.get('date')} в {a.get('time')}"
    ),
    "confirm_payment_sent": lambda a: f"Подтвердить отправку оплаты по записи #{a.get('booking_id')}",
    "cancel_my_booking": lambda a: f"Отменить запись #{a.get('booking_id')}",
    "reschedule_my_booking": lambda a: (
        f"Перенести запись #{a.get('booking_id')} на {a.get('new_date')} в {a.get('new_time')}"
    ),
}


# ─── Context builder (self-contained, no bot imports) ─────────────────────────

async def _build_client_context(db: AsyncSession, user: User) -> dict:
    """Build context packet for client AI prompt, same structure as get_client_context."""
    res = await db.execute(select(Business).where(Business.is_active.is_(True)))
    bizs = res.scalars().all()

    businesses = []
    for b in bizs:
        # Services
        svc_res = await db.execute(
            select(Service).where(
                Service.business_id == b.id,
                Service.is_active.is_(True),
            )
        )
        services = [
            {"id": s.id, "name": s.name, "price": s.price,
             "duration": s.duration_minutes, "is_additional": s.is_additional or False}
            for s in svc_res.scalars().all()
        ]

        # Employees
        emp_res = await db.execute(
            select(Employee).where(
                Employee.business_id == b.id,
                Employee.is_active.is_(True),
            )
        )
        employees = [
            {"id": e.id, "name": e.name, "role": e.role or "master",
             "specialization": e.specialization or ""}
            for e in emp_res.scalars().all()
        ]

        wh = ""
        if b.working_hours_start and b.working_hours_end:
            wh = f"{b.working_hours_start.strftime('%H:%M')}\u2013{b.working_hours_end.strftime('%H:%M')}"

        businesses.append({
            "id": b.id, "name": b.name, "address": b.address or "",
            "working_hours": wh,
            "business_type": b.business_type or "",
            "prepayment_enabled": bool(b.prepayment_enabled and b.payment_phone),
            "prepayment_percent": b.prepayment_percent,
            "has_cancellation_policy": bool(b.cancellation_policy_photo),
            "services": services,
            "employees": employees,
        })

    # AI instructions
    ai_instructions: dict = {}
    for b in bizs:
        if getattr(b, "ai_instruction", None) and b.ai_instruction.strip():
            ai_instructions["business"] = b.ai_instruction.strip()
    svc_ai = []
    emp_ai = []
    for b in bizs:
        svc_res2 = await db.execute(
            select(Service).where(Service.business_id == b.id, Service.is_active.is_(True))
        )
        for s in svc_res2.scalars().all():
            if getattr(s, "ai_instruction", None) and s.ai_instruction.strip():
                svc_ai.append({"name": s.name, "instruction": s.ai_instruction.strip()})
        emp_res2 = await db.execute(
            select(Employee).where(Employee.business_id == b.id, Employee.is_active.is_(True))
        )
        for e in emp_res2.scalars().all():
            if getattr(e, "ai_instruction", None) and e.ai_instruction.strip():
                emp_ai.append({"name": e.name, "instruction": e.ai_instruction.strip()})
    if svc_ai:
        ai_instructions["services"] = svc_ai
    if emp_ai:
        ai_instructions["employees"] = emp_ai

    # Client bookings (upcoming)
    today = datetime.date.today()
    bk_res = await db.execute(
        select(Booking)
        .options(selectinload(Booking.service), selectinload(Booking.business))
        .where(and_(
            Booking.client_id == user.id,
            Booking.booking_date >= today,
            Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
        ))
        .order_by(Booking.booking_date, Booking.booking_time)
        .limit(10)
    )
    client_bookings = [
        {
            "id": bk.id,
            "business_name": bk.business.name if bk.business else "\u2014",
            "service_name": bk.service.name if bk.service else "\u2014",
            "date": str(bk.booking_date),
            "time": bk.booking_time.strftime("%H:%M"),
            "status": bk.status,
        }
        for bk in bk_res.scalars().all()
    ]

    return {
        "businesses": businesses,
        "client_bookings": client_bookings,
        "ai_instructions": ai_instructions,
    }


# ─── Read-only tool execution ────────────────────────────────────────────────

async def _exec_get_available_slots(db: AsyncSession, args: dict) -> str:
    """Compute available slots for a business/service/date."""
    from datetime import timedelta

    business_id = int(args["business_id"])
    service_id = int(args["service_id"])
    date_str = args["date"]
    employee_id = int(args["employee_id"]) if args.get("employee_id") else None

    target_date = datetime.date.fromisoformat(date_str)

    res = await db.execute(select(Business).where(Business.id == business_id))
    business = res.scalar_one_or_none()
    if not business:
        return "Заведение не найдено"

    res = await db.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if not service:
        return "Услуга не найдена"

    interval = business.booking_interval_minutes or 30
    duration = service.duration_minutes or 30
    start_t = business.working_hours_start or datetime.time(9, 0)
    end_t = business.working_hours_end or datetime.time(21, 0)

    # Determine which employees to check
    if employee_id:
        emp_ids = [employee_id]
    else:
        res = await db.execute(
            select(EmployeeService.employee_id)
            .where(EmployeeService.service_id == service_id)
        )
        emp_ids = [r[0] for r in res.fetchall()]
        if not emp_ids:
            res = await db.execute(
                select(Employee.id).where(and_(
                    Employee.business_id == business_id,
                    Employee.is_active.is_(True),
                ))
            )
            emp_ids = [r[0] for r in res.fetchall()]

    # Get existing bookings for the date
    res = await db.execute(
        select(Booking).options(selectinload(Booking.service)).where(and_(
            Booking.business_id == business_id,
            Booking.booking_date == target_date,
            Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
        ))
    )
    bookings = res.scalars().all()

    def is_employee_free(eid: int, slot_start: datetime.datetime) -> bool:
        slot_end = slot_start + timedelta(minutes=duration)
        for bk in bookings:
            if bk.employee_id != eid:
                continue
            bk_start = datetime.datetime.combine(target_date, bk.booking_time)
            bk_dur = bk.service.duration_minutes if bk.service else 30
            bk_end = bk_start + timedelta(minutes=bk_dur)
            if not (slot_end <= bk_start or slot_start >= bk_end):
                return False
        return True

    now = datetime.datetime.now()
    current = datetime.datetime.combine(target_date, start_t)
    end_dt = datetime.datetime.combine(target_date, end_t)

    # If today, skip past slots
    if target_date == now.date():
        min_start = now + timedelta(hours=1)
        if current < min_start:
            mins = (min_start.minute // interval + 1) * interval
            if mins >= 60:
                current = min_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                current = min_start.replace(minute=mins, second=0, microsecond=0)

    available = []
    while current + timedelta(minutes=duration) <= end_dt:
        in_break = False
        if business.break_start and business.break_end:
            if business.break_start <= current.time() < business.break_end:
                in_break = True
        if not in_break:
            if not emp_ids or any(is_employee_free(eid, current) for eid in emp_ids):
                available.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)

    if not available:
        return f"На {date_str} нет свободных слотов. Попробуйте другую дату."
    return f"Свободное время на {date_str}:\n" + ", ".join(available)


async def _exec_get_my_bookings(db: AsyncSession, args: dict, user_id: int) -> str:
    """Get client's bookings."""
    status_filter = args.get("status", "upcoming")
    q = (
        select(Booking)
        .options(selectinload(Booking.service), selectinload(Booking.business))
        .where(Booking.client_id == user_id)
    )
    today = datetime.date.today()
    if status_filter == "upcoming":
        q = q.where(and_(
            Booking.booking_date >= today,
            Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
        ))
    elif status_filter == "cancelled":
        q = q.where(Booking.status == "cancelled")
    q = q.order_by(Booking.booking_date, Booking.booking_time).limit(15)
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return "Записей не найдено"
    icons = {"pending": "ожидает", "confirmed": "подтверждена", "cancelled": "отменена",
             "completed": "завершена", "pending_prepayment": "ожидает оплаты",
             "prepayment_sent": "оплата на проверке"}
    lines = ["Ваши записи:\n"]
    for b in rows:
        svc = b.service.name if b.service else "-"
        biz = b.business.name if b.business else "-"
        status_label = icons.get(b.status, b.status)
        lines.append(
            f"#{b.id} | {b.booking_date} "
            f"{b.booking_time.strftime('%H:%M')} | {biz} — {svc} ({status_label})"
        )
    return "\n".join(lines)


async def _exec_get_additional_services(db: AsyncSession, args: dict) -> str:
    """Get additional services for a venue business."""
    business_id = int(args["business_id"])
    res = await db.execute(select(Business).where(Business.id == business_id))
    biz = res.scalar_one_or_none()
    if not biz:
        return "Заведение не найдено"

    # Check if venue rental type
    venue_types = {"venue_rental", "sport_venue", "coworking", "banquet_hall",
                   "photo_studio", "recording_studio", "event_space"}
    if biz.business_type not in venue_types:
        return "Дополнительные услуги доступны только для аренды помещений"

    res = await db.execute(
        select(Service).where(and_(
            Service.business_id == business_id,
            Service.is_active.is_(True),
            Service.is_additional.is_(True),
        ))
    )
    additional = res.scalars().all()
    if not additional:
        return "Дополнительных услуг нет"
    lines = ["Дополнительные услуги:\n"]
    for svc in additional:
        if svc.is_hourly_price:
            price_info = f", {svc.price} руб/час" if svc.price else ""
        else:
            price_info = f", {svc.price} руб" if svc.price else ""
        lines.append(f"#{svc.id} {svc.name} ({svc.duration_minutes} мин{price_info})")
    return "\n".join(lines)


async def _execute_read_tool(db: AsyncSession, tool_name: str, args: dict, user_id: int) -> str:
    """Execute a read-only tool and return the result string."""
    try:
        if tool_name == "get_available_slots":
            return await _exec_get_available_slots(db, args)
        elif tool_name == "get_my_bookings":
            return await _exec_get_my_bookings(db, args, user_id)
        elif tool_name == "get_additional_services":
            return await _exec_get_additional_services(db, args)
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as exc:
        logger.error("Read tool %s failed: %s", tool_name, exc, exc_info=True)
        return f"Error executing {tool_name}: {exc}"


# ─── Mutation tool execution ─────────────────────────────────────────────────

async def _execute_mutation(db: AsyncSession, tool_name: str, args: dict, user_id: int) -> str:
    """Execute a confirmed mutation tool. Returns result string."""
    try:
        if tool_name == "create_booking":
            return await _exec_create_booking(db, args, user_id)
        elif tool_name == "confirm_payment_sent":
            return await _exec_confirm_payment(db, args, user_id)
        elif tool_name == "cancel_my_booking":
            return await _exec_cancel_booking(db, args, user_id)
        elif tool_name == "reschedule_my_booking":
            return await _exec_reschedule_booking(db, args, user_id)
        else:
            return f"Unknown mutation: {tool_name}"
    except Exception as exc:
        logger.error("Mutation %s failed: %s", tool_name, exc, exc_info=True)
        return f"Error: {exc}"


async def _exec_create_booking(db: AsyncSession, args: dict, client_id: int) -> str:
    """Create a booking in DB."""
    biz_id = int(args["business_id"])
    svc_id = int(args["service_id"])
    book_date = datetime.date.fromisoformat(args["date"])
    book_time = datetime.datetime.strptime(args["time"], "%H:%M").time()

    res = await db.execute(select(Business).where(Business.id == biz_id))
    business = res.scalar_one_or_none()
    if not business:
        return "Заведение не найдено"

    res = await db.execute(select(Service).where(Service.id == svc_id))
    service = res.scalar_one_or_none()
    if not service:
        return "Услуга не найдена"

    need_prepayment = (
        business.prepayment_enabled
        and business.payment_phone
        and service.price
        and service.price > 0
    )
    initial_status = "pending_prepayment" if need_prepayment else "confirmed"

    employee_id = int(args["employee_id"]) if args.get("employee_id") else None

    booking = Booking(
        business_id=biz_id,
        client_id=client_id,
        service_id=svc_id,
        booking_date=book_date,
        booking_time=book_time,
        employee_id=employee_id,
        notes=args.get("notes"),
        status=initial_status,
    )
    db.add(booking)
    await db.flush()

    # Additional services
    additional_ids = args.get("additional_service_ids") or []
    for add_id in additional_ids:
        add_booking = Booking(
            business_id=biz_id,
            client_id=client_id,
            service_id=int(add_id),
            booking_date=book_date,
            booking_time=book_time,
            employee_id=employee_id,
            status=initial_status,
        )
        db.add(add_booking)

    await db.commit()

    biz_name = args.get("business_name") or business.name
    svc_name = args.get("service_name") or service.name

    # Notify owner via Telegram Bot API (fire-and-forget)
    _schedule_owner_notification(business, booking, service)

    if need_prepayment:
        pp_pct = business.prepayment_percent or 100
        pp_amount = int(service.price * pp_pct / 100)
        response = (
            f"Запись создана!\n"
            f"{biz_name}\n"
            f"{args['date']} в {args['time']}\n"
            f"{svc_name}\n"
            f"#{booking.id}\n\n"
            f"Требуется предоплата: {pp_amount} руб."
            + (f" ({pp_pct}% от {service.price} руб.)" if pp_pct < 100 else "")
            + f"\nПеревести на номер: {business.payment_phone}"
        )
        if business.payment_details:
            response += f"\nРеквизиты: {business.payment_details}"
        response += "\n\nПосле перевода скажите 'оплатил' и я уведомлю заведение."
        return response

    return (
        f"Запись подтверждена!\n"
        f"{biz_name}\n"
        f"{args['date']} в {args['time']}\n"
        f"{svc_name}\n"
        f"#{booking.id}"
    )


async def _exec_confirm_payment(db: AsyncSession, args: dict, client_id: int) -> str:
    booking_id = int(args["booking_id"])
    res = await db.execute(
        select(Booking)
        .options(selectinload(Booking.business), selectinload(Booking.service))
        .where(and_(Booking.id == booking_id, Booking.client_id == client_id))
    )
    bk = res.scalar_one_or_none()
    if not bk:
        return "Запись не найдена"
    if bk.status not in ("pending_prepayment",):
        return f"Статус записи: {bk.status}. Подтверждение уже было отправлено."
    bk.status = "prepayment_sent"
    await db.commit()

    # Notify owner via Telegram Bot API
    if bk.business:
        _schedule_owner_payment_notification(bk)

    return f"Отлично! Уведомили заведение о вашей оплате по записи #{booking_id}."


async def _exec_cancel_booking(db: AsyncSession, args: dict, client_id: int) -> str:
    booking_id = int(args["booking_id"])
    res = await db.execute(
        select(Booking).where(and_(Booking.id == booking_id, Booking.client_id == client_id))
    )
    bk = res.scalar_one_or_none()
    if not bk:
        return "Запись не найдена или не принадлежит вам"
    if bk.status == "cancelled":
        return "Запись уже отменена"
    bk.status = "cancelled"
    reason = args.get("reason")
    if reason:
        bk.notes = (bk.notes or "") + f"\nОтменено клиентом: {reason}"
    await db.commit()
    return f"Запись #{booking_id} отменена"


async def _exec_reschedule_booking(db: AsyncSession, args: dict, client_id: int) -> str:
    from datetime import timedelta
    booking_id = int(args["booking_id"])
    res = await db.execute(
        select(Booking).options(selectinload(Booking.service))
        .where(and_(Booking.id == booking_id, Booking.client_id == client_id))
    )
    bk = res.scalar_one_or_none()
    if not bk:
        return "Запись не найдена или не принадлежит вам"
    new_date_str = args["new_date"]
    new_time_str = args["new_time"]
    new_date = datetime.date.fromisoformat(new_date_str)
    new_time = datetime.datetime.strptime(new_time_str, "%H:%M").time()

    # Check for conflicts
    duration = bk.service.duration_minutes if bk.service else 30
    new_start = datetime.datetime.combine(new_date, new_time)
    new_end = new_start + timedelta(minutes=duration)

    conflict_res = await db.execute(
        select(Booking).options(selectinload(Booking.service)).where(and_(
            Booking.business_id == bk.business_id,
            Booking.booking_date == new_date,
            Booking.employee_id == bk.employee_id,
            Booking.id != booking_id,
            Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
        ))
    )
    for existing in conflict_res.scalars().all():
        ex_start = datetime.datetime.combine(new_date, existing.booking_time)
        ex_dur = existing.service.duration_minutes if existing.service else 30
        ex_end = ex_start + timedelta(minutes=ex_dur)
        if not (new_end <= ex_start or new_start >= ex_end):
            return f"Время {new_time_str} на {new_date_str} уже занято. Выберите другое время."

    bk.booking_date = new_date
    bk.booking_time = new_time
    await db.commit()
    return f"Запись #{booking_id} перенесена на {new_date_str} в {new_time_str}"


def _schedule_owner_notification(business: Business, booking: Booking, service: Service):
    """Fire-and-forget notification to owner via Telegram Bot API."""
    import asyncio

    bot_token = os.getenv("BOT_TOKEN", "***REMOVED***")

    async def _send():
        try:
            async with httpx.AsyncClient() as client:
                # Get owner telegram_id
                from ..database import async_session
                async with async_session() as s:
                    res = await s.execute(select(User).where(User.id == business.owner_id))
                    owner = res.scalar_one_or_none()
                    if not owner or not owner.telegram_id:
                        return
                    text = (
                        f"Новая запись (web)!\n"
                        f"{service.name}\n"
                        f"{booking.booking_date} в {booking.booking_time.strftime('%H:%M')}\n"
                        f"#{booking.id}"
                    )
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": owner.telegram_id, "text": text},
                        timeout=10,
                    )
        except Exception as e:
            logger.warning("Failed to notify owner: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        pass


def _schedule_owner_payment_notification(booking: Booking):
    """Fire-and-forget payment notification to owner."""
    import asyncio

    bot_token = os.getenv("BOT_TOKEN", "***REMOVED***")

    async def _send():
        try:
            async with httpx.AsyncClient() as client:
                from ..database import async_session
                async with async_session() as s:
                    res = await s.execute(select(User).where(User.id == booking.business.owner_id))
                    owner = res.scalar_one_or_none()
                    if not owner or not owner.telegram_id:
                        return
                    text = (
                        f"Клиент отправил предоплату!\n"
                        f"Запись #{booking.id}\n"
                        f"{booking.booking_date} в {booking.booking_time.strftime('%H:%M')}\n"
                        f"Пожалуйста, проверьте оплату."
                    )
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": owner.telegram_id, "text": text},
                        timeout=10,
                    )
        except Exception as e:
            logger.warning("Failed to notify owner about payment: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        pass


# ─── OpenRouter API call ─────────────────────────────────────────────────────

async def _call_openrouter(messages: list[dict], tools: list[dict]) -> dict:
    """Call OpenRouter API with model fallback. Returns the response message dict."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    async with httpx.AsyncClient(timeout=60) as client:
        for model in MODELS:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": TEMPERATURE,
                    "max_tokens": 1024,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
                if resp.status_code != 200:
                    last_error = f"Model {model}: HTTP {resp.status_code} - {resp.text[:200]}"
                    logger.warning("OpenRouter %s returned %d", model, resp.status_code)
                    continue

                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    last_error = f"Model {model}: empty choices"
                    continue

                return choices[0]["message"]

            except Exception as e:
                last_error = f"Model {model}: {e}"
                logger.warning("OpenRouter %s error: %s", model, e)
                continue

    raise HTTPException(status_code=502, detail=f"All AI models failed. Last error: {last_error}")


# ─── System prompt builder ───────────────────────────────────────────────────

def _build_system_prompt(context: dict) -> str:
    """Build system prompt using the same logic as client_admin.py."""
    try:
        from bot.prompts.client_admin import build_client_system_prompt
        return build_client_system_prompt(context)
    except ImportError:
        logger.warning("Could not import prompt builder, using inline version")
        return _inline_system_prompt(context)


def _inline_system_prompt(context: dict) -> str:
    """Fallback inline system prompt if import fails."""
    today_date = datetime.date.today()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    today = today_date.strftime("%d.%m.%Y (%A)")
    today_iso = today_date.strftime("%Y-%m-%d")
    tomorrow_iso = tomorrow_date.strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%H:%M")

    businesses = context.get("businesses", [])
    client_bookings = context.get("client_bookings", [])

    biz_blocks = []
    for b in businesses:
        header = b["name"]
        if b.get("address"):
            header += f', {b["address"]}'
        if b.get("working_hours"):
            header += f', {b["working_hours"]}'
        svc_lines = []
        for svc in b.get("services", []):
            if svc.get("is_additional"):
                continue
            parts = [svc["name"]]
            if svc.get("price"):
                parts.append(f'{svc["price"]} руб.')
            if svc.get("duration"):
                parts.append(f'{svc["duration"]} мин')
            svc_lines.append(f'  #{svc["id"]}: {" - ".join(parts)}')
        emp_lines = []
        for emp in b.get("employees", []):
            if emp.get("role") == "administrator":
                continue
            spec = f' ({emp["specialization"]})' if emp.get("specialization") else ""
            emp_lines.append(f'  @{emp["id"]}: {emp["name"]}{spec}')
        block = f'[B{b["id"]}] {header}'
        if svc_lines:
            block += "\n  Услуги:\n" + "\n".join(svc_lines)
        if emp_lines:
            block += "\n  Мастера:\n" + "\n".join(emp_lines)
        biz_blocks.append(block)

    bookings_text = ""
    if client_bookings:
        lines = []
        for bk in client_bookings:
            lines.append(f'  #{bk["id"]} {bk["date"]} {bk["time"]} {bk["business_name"]} - {bk["service_name"]}')
        bookings_text = "\nЗаписи клиента:\n" + "\n".join(lines)

    return (
        f"Ты — AI-помощник сервиса онлайн-записи SochiService. Общайся на русском языке, дружелюбно и по делу.\n\n"
        f"Сегодня: {today}, ISO: {today_iso}, завтра: {tomorrow_iso}, время: {now}.\n"
        f"Клиент уже в системе — НЕ спрашивай имя, телефон, email.\n\n"
        f"<context>\n{chr(10).join(biz_blocks)}\n{bookings_text}\n</context>\n\n"
        f"Твои возможности:\n"
        f"- Показать доступные салоны/услуги и свободное время\n"
        f"- Записать клиента на услугу\n"
        f"- Показать записи клиента\n"
        f"- Перенести или отменить запись\n"
        f"- Ответить на вопросы о салонах, услугах, ценах\n\n"
        f"Используй tools для работы с записями. Отвечай развёрнуто, но не более 3-4 предложений."
    )


# ─── Main chat endpoint ──────────────────────────────────────────────────────

@router.post("/ai/chat", response_model=AIChatOut)
async def ai_chat(
    body: AIChatIn,
    user: User = Depends(_get_ai_user),
    db: AsyncSession = Depends(get_db),
):
    """
    AI chat endpoint with agentic tool loop.
    Read-only tools are auto-executed; mutation tools require user confirmation.
    """
    user_id = user.id

    # Build context and system prompt
    context = await _build_client_context(db, user)
    system_prompt = _build_system_prompt(context)

    # Get or init conversation history
    if user_id not in _histories:
        _histories[user_id] = []
    history = _histories[user_id]

    # Add user message
    history.append({"role": "user", "content": body.message})

    # Trim history if too long
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    # Build messages for API call
    messages = [{"role": "system", "content": system_prompt}] + history

    # Agentic loop: call AI, execute read-only tools, re-call AI
    for iteration in range(MAX_LOOPS):
        ai_message = await _call_openrouter(messages, CLIENT_TOOL_SCHEMAS)

        # Check for tool calls
        tool_calls = ai_message.get("tool_calls")
        if not tool_calls:
            # No tool calls - return the text response
            reply_text = ai_message.get("content") or ""
            history.append({"role": "assistant", "content": reply_text})
            return AIChatOut(reply=reply_text)

        # Process tool calls
        # Add assistant message with tool calls to history
        assistant_msg = {"role": "assistant", "content": ai_message.get("content") or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        history.append(assistant_msg)
        messages.append(assistant_msg)

        # Check if any mutation tool is called
        pending_action = None
        all_read_only = True

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                tool_args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name in READ_ONLY_TOOLS:
                # Execute read-only tool immediately
                result = await _execute_read_tool(db, tool_name, tool_args, user_id)
                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                }
                history.append(tool_result_msg)
                messages.append(tool_result_msg)

            elif tool_name in MUTATION_TOOLS:
                all_read_only = False
                # Enrich args with names from DB for human-readable description
                if tool_name == "create_booking":
                    if not tool_args.get("service_name") and tool_args.get("service_id"):
                        svc_r = await db.execute(select(Service).where(Service.id == tool_args["service_id"]))
                        svc_obj = svc_r.scalar_one_or_none()
                        if svc_obj:
                            tool_args["service_name"] = svc_obj.name
                    if not tool_args.get("business_name") and tool_args.get("business_id"):
                        biz_r = await db.execute(select(Business).where(Business.id == tool_args["business_id"]))
                        biz_obj = biz_r.scalar_one_or_none()
                        if biz_obj:
                            tool_args["business_name"] = biz_obj.name
                # Store as pending action for user confirmation
                action_id = str(uuid.uuid4())
                desc_fn = MUTATION_DESCRIPTIONS.get(tool_name)
                description = desc_fn(tool_args) if desc_fn else f"Execute: {tool_name}"

                _pending[action_id] = {
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "tool_call_id": tc.get("id", ""),
                }

                pending_action = {
                    "action_id": action_id,
                    "description": description,
                    "tool_name": tool_name,
                    "args": tool_args,
                }

                # Provide a synthetic tool response so the conversation stays consistent
                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": f"[ACTION PENDING USER CONFIRMATION: {description}]",
                }
                history.append(tool_result_msg)
                messages.append(tool_result_msg)
            else:
                # Unknown tool
                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": f"Unknown tool: {tool_name}",
                }
                history.append(tool_result_msg)
                messages.append(tool_result_msg)

        if not all_read_only and pending_action:
            # We have a mutation pending - get the AI to produce a confirmation message
            # by continuing the loop once more, but then break
            ai_message = await _call_openrouter(messages, [])  # no tools on confirmation round
            reply_text = ai_message.get("content") or pending_action["description"]
            history.append({"role": "assistant", "content": reply_text})
            return AIChatOut(reply=reply_text, pending_action=pending_action)

        # If all read-only, continue the loop so the AI gets the tool results
        # and can either call more tools or produce a final response

    # If we exhaust loops, return whatever we have
    return AIChatOut(reply="Извините, не удалось обработать запрос. Попробуйте снова.")


# ─── Confirm mutation endpoint ────────────────────────────────────────────────

@router.post("/ai/confirm", response_model=AIChatOut)
async def ai_confirm(
    body: AIConfirmIn,
    user: User = Depends(_get_ai_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm and execute a pending mutation action.
    Called after user approves an action proposed by AI.
    """
    action = _pending.pop(body.action_id, None)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found or already executed")

    if action["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Action belongs to another user")

    result = await _execute_mutation(db, action["tool_name"], action["args"], user.id)

    # Update conversation history with the real tool result
    user_id = user.id
    history = _histories.get(user_id, [])

    # Replace the synthetic pending message with real result in history
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if (msg.get("role") == "tool"
                and msg.get("tool_call_id") == action.get("tool_call_id")
                and "ACTION PENDING" in msg.get("content", "")):
            history[i]["content"] = result
            break

    # Add the result as a user-visible message
    history.append({"role": "assistant", "content": result})

    return AIChatOut(reply=result)


# ─── Reject mutation endpoint ────────────────────────────────────────────────

@router.post("/ai/reject")
async def ai_reject(
    body: AIConfirmIn,
    user: User = Depends(_get_ai_user),
):
    """Reject a pending mutation action."""
    action = _pending.pop(body.action_id, None)
    if not action:
        return {"message": "Действие не найдено или уже обработано"}

    # Clean up conversation history — remove the pending tool result
    user_id = user.id
    history = _histories.get(user_id, [])
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if (msg.get("role") == "tool"
                and msg.get("tool_call_id") == action.get("tool_call_id")
                and "ACTION PENDING" in msg.get("content", "")):
            history[i]["content"] = "Пользователь отменил это действие."
            break

    return {"message": "Действие отменено"}


# ─── Clear history endpoint ──────────────────────────────────────────────────

@router.post("/ai/clear")
async def ai_clear_history(user: User = Depends(_get_ai_user)):
    """Clear conversation history for the current user."""
    user_id = user.id
    _histories.pop(user_id, None)
    # Clean up any pending actions for this user
    to_remove = [k for k, v in _pending.items() if v["user_id"] == user_id]
    for k in to_remove:
        _pending.pop(k, None)
    return {"ok": True}
