"""
Client-facing routes: browse businesses, view slots, create/cancel bookings.
"""
from datetime import datetime, date, time, timedelta
from typing import List, Optional

import asyncio
import json
import logging
import os
import httpx
import uuid

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..photo_transport import create_photo_client
from ..database import get_db, Business, Service, Employee, EmployeeService, Booking, User, VenueTimePricing
from ..deps import get_current_user, get_current_user_optional
from database.crud import get_or_create_guest_user
from ..booking_utils import compute_recurring_dates
from ..schemas import (
    BusinessOut,
    BusinessDetailOut,
    ServiceOut,
    EmployeeOut,
    TimePricingOut,
    SlotOut,
    CreateBookingIn,
    BookingOut,
    CalculatePriceOut,
    PriceSegment,
    RescheduleIn,
    PublicBookingOut,
    PublicServiceItem,
)

router = APIRouter()


# ---------- helpers ----------


BOOKING_LABEL_KEYS = {"service", "resource", "additional_services", "date", "time"}


def _parse_booking_labels(raw) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, label in value.items():
        if key in BOOKING_LABEL_KEYS and isinstance(label, str) and label.strip():
            result[key] = label.strip()[:80]
    return result


async def _build_prepayment_owner_msg(booking: Booking, db: AsyncSession, receipt_note: str = None) -> str:
    """Build prepayment owner notification — SAME format as bot's _build_prepayment_owner_text."""
    from bot.utils.business_types import is_venue_rental_type, get_terminology

    business = booking.business
    client = booking.client

    # Find all related bookings for this visit (same as bot)
    related_result = await db.execute(
        select(Booking).options(
            selectinload(Booking.service),
            selectinload(Booking.employee),
        ).where(
            Booking.client_id == booking.client_id,
            Booking.business_id == booking.business_id,
            Booking.employee_id == booking.employee_id,
            Booking.booking_date == booking.booking_date,
            Booking.booking_time == booking.booking_time,
            Booking.status.in_(["pending_prepayment", "prepayment_sent"]),
        )
    )
    related_bookings = list(related_result.scalars().all())
    if not related_bookings:
        related_bookings = [booking]

    is_venue = is_venue_rental_type(business.business_type)
    term = get_terminology(business.business_type)
    emp_label = term.get("employee", "Мастер")

    # Client link
    if client.telegram_id and client.telegram_id > 0:
        client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'
    else:
        client_link = client.full_name or "Клиент"

    text = (
        f"💳 <b>Клиент отправил предоплату!</b>\n\n"
        f"🏢 {business.name}\n"
        f"📅 {booking.booking_date.strftime('%d.%m.%Y')} в {booking.booking_time.strftime('%H:%M')}\n\n"
        f"👤 Клиент: {client_link}\n"
    )

    if client.phone:
        clean = ''.join(c for c in client.phone if c.isdigit() or c == '+')
        if clean.startswith('+'):
            clean = clean[1:]
        if len(clean) == 10:
            fmt = f"+7{clean}"
        elif len(clean) == 11 and clean.startswith('7'):
            fmt = f"+7{clean[1:]}"
        else:
            fmt = client.phone
        tel_link = fmt if fmt.startswith('+') else '+7' + fmt[1:]
        text += f'📱 Телефон: <a href="tel:{tel_link}">{fmt}</a>\n'

    # Collect services
    main_services = []
    additional_services = []
    total_price = 0
    total_duration = 0
    employee_info = None

    for bk in related_bookings:
        if bk.service:
            svc = bk.service
            if getattr(svc, 'is_additional', False):
                additional_services.append(svc)
            else:
                main_services.append(svc)
                total_duration += svc.duration_minutes or 0
            total_price += svc.price or 0
        if bk.employee and not employee_info:
            employee_info = bk.employee

    all_services = main_services + additional_services
    if len(all_services) > 1:
        text += "\n💼 Услуги:\n"
        for svc in main_services:
            price_str = f" - {svc.price}₽" if svc.price else ""
            text += f"  • {svc.name} ({svc.duration_minutes} мин{price_str})\n"
        if additional_services:
            text += "\n  📎 Доп. услуги:\n"
            for svc in additional_services:
                price_str = f" - {svc.price}₽" if svc.price else ""
                text += f"  • {svc.name} ({svc.duration_minutes} мин{price_str})\n"
        text += f"\n⏱ Общая длительность: {total_duration} мин\n"
        if total_price > 0:
            text += f"💰 Общая сумма: {total_price}₽\n"
    else:
        svc = booking.service
        text += f"\n💼 Услуга: {svc.name} ({svc.duration_minutes} мин)\n"
        if svc.price:
            total_price = svc.price
            text += f"💰 Сумма: {svc.price}₽\n"

    # Employee/venue
    emp = employee_info or booking.employee
    if emp:
        if is_venue:
            text += f"\n🏠 Помещение: {emp.name}\n"
        else:
            text += f"\n👔 {emp_label}: {emp.name}\n"

    # Prepayment amount
    prepay_amount = getattr(booking, 'prepayment_amount', None)
    prepay_pct = business.prepayment_percent or 100
    if not prepay_amount:
        prepay_amount = int(total_price * prepay_pct / 100)
    text += f"\n💰 <b>Сумма предоплаты: {prepay_amount}₽</b>"
    if prepay_pct < 100 and total_price > 0:
        text += f" ({prepay_pct}% от {total_price}₽)"
    text += "\n"

    if booking.notes:
        text += f"\n💬 Комментарий: {booking.notes}\n"

    if receipt_note:
        text += f"\n{receipt_note}\n"

    text += "\nПроверьте получение оплаты и подтвердите или отклоните."
    return text

def _business_to_out(biz: Business, services_count: int = 0) -> BusinessOut:
    return BusinessOut(
        id=biz.id,
        name=biz.name,
        description=biz.description,
        business_type=biz.business_type,
        address=biz.address,
        phone=biz.phone,
        working_hours_start=biz.working_hours_start,
        working_hours_end=biz.working_hours_end,
        photos=biz.photos,
        services_count=services_count,
    )


def _booking_to_out(b: Booking, can_cancel: bool = False, can_reschedule: bool = False) -> BookingOut:
    return BookingOut(
        id=b.id,
        business_id=b.business_id,
        service_id=b.service_id,
        business_name=b.business.name if b.business else "",
        service_name=b.service.name if b.service else "",
        service_price=b.service.price if b.service else None,
        business_address=b.business.address if b.business else None,
        duration_minutes=(b.duration_minutes or (b.service.duration_minutes if b.service else None)),
        date=b.booking_date,
        time=b.booking_time.strftime("%H:%M"),
        status=b.status,
        employee_name=b.employee.name if b.employee else None,
        notes=b.notes,
        created_at=b.created_at,
        can_cancel=can_cancel,
        can_reschedule=can_reschedule,
        notify_token=b.notify_token,
    )


def _service_to_out(service: Service) -> ServiceOut:
    """Convert Service model to ServiceOut, parsing group_pricing JSON.

    `group_pricing` is stored as a JSON-encoded string (Text column) —
    ServiceOut.model_validate(service) would hand that raw string straight
    to the List[GroupPricingTier] field and fail Pydantic validation.
    """
    data = {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "duration_minutes": service.duration_minutes,
        "price": service.price,
        "is_active": service.is_active,
        "is_additional": service.is_additional,
        "is_hourly_price": service.is_hourly_price,
        "sort_order": service.sort_order,
        "pricing_type": getattr(service, 'pricing_type', 'fixed') or 'fixed',
    }
    gp = getattr(service, 'group_pricing', None)
    if gp:
        try:
            data["group_pricing"] = json.loads(gp) if isinstance(gp, str) else gp
        except (json.JSONDecodeError, TypeError):
            data["group_pricing"] = None
    return ServiceOut(**data)


def _employee_to_out(e: Employee, pricing_rules: list = None) -> EmployeeOut:
    tp_list = []
    if pricing_rules:
        for r in pricing_rules:
            tp_list.append(TimePricingOut(
                time_from=r.time_from.strftime("%H:%M"),
                time_to=r.time_to.strftime("%H:%M"),
                price_per_hour=r.price_per_hour,
                day_type=r.day_type or "all",
            ))
    return EmployeeOut(
        id=e.id,
        name=e.name,
        role=getattr(e, 'role', 'master') or 'master',
        specialization=e.specialization,
        description=getattr(e, 'description', None),
        capacity=getattr(e, 'capacity', None),
        area_sqm=getattr(e, 'area_sqm', None),
        solo_price_per_hour=getattr(e, 'solo_price_per_hour', None),
        photos=getattr(e, 'photos', None),
        primary_photo=getattr(e, 'primary_photo', None),
        service_ids=[link.service_id for link in getattr(e, 'employee_services', [])],
        venue_time_pricing=tp_list,
    )


def _can_modify_booking(b: Booking) -> tuple:
    """Check if booking can be cancelled/rescheduled (must be future, not cancelled)."""
    if b.status in ("cancelled", "completed"):
        return False, False
    booking_dt = datetime.combine(b.booking_date, b.booking_time)
    now = datetime.now()
    if booking_dt <= now:
        return False, False
    # Allow cancel/reschedule if more than 2 hours before
    can = booking_dt > now + timedelta(hours=2)
    return can, can


# ---------- GET /businesses ----------

@router.get("/businesses", response_model=List[BusinessOut])
async def list_businesses(db: AsyncSession = Depends(get_db)):
    """List all active businesses with service counts."""
    result = await db.execute(
        select(Business)
        .where(Business.is_active == True)
        .options(selectinload(Business.services))
    )
    businesses = result.scalars().all()

    return [
        _business_to_out(
            biz,
            services_count=sum(1 for s in biz.services if s.is_active),
        )
        for biz in businesses
    ]


# ---------- GET /businesses/{id} ----------

@router.get("/businesses/{business_id}", response_model=BusinessDetailOut)
async def get_business(business_id: int, db: AsyncSession = Depends(get_db)):
    """Business detail: info + active services + active employees (masters only)."""
    result = await db.execute(
        select(Business)
        .where(Business.id == business_id)
        .options(
            selectinload(Business.services),
            selectinload(Business.employees).selectinload(Employee.employee_services),
        )
    )
    biz = result.scalar_one_or_none()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    active_services = [s for s in biz.services if s.is_active]
    # Filter out admin employees — only show masters/specialists to clients
    active_employees = [
        e for e in biz.employees
        if e.is_active and getattr(e, 'role', 'master') != 'admin'
    ]

    # Fetch venue_time_pricing for all active employees
    emp_ids = [e.id for e in active_employees]
    pricing_by_emp = {}
    if emp_ids:
        pricing_result = await db.execute(
            select(VenueTimePricing).where(VenueTimePricing.employee_id.in_(emp_ids))
        )
        for p in pricing_result.scalars().all():
            pricing_by_emp.setdefault(p.employee_id, []).append(p)

    return BusinessDetailOut(
        id=biz.id,
        name=biz.name,
        description=biz.description,
        business_type=biz.business_type,
        address=biz.address,
        phone=biz.phone,
        working_hours_start=biz.working_hours_start,
        working_hours_end=biz.working_hours_end,
        break_start=biz.break_start,
        break_end=biz.break_end,
        photos=biz.photos,
        directions=biz.directions,
        services_count=len(active_services),
        services=[_service_to_out(s) for s in active_services],
        employees=[_employee_to_out(e, pricing_by_emp.get(e.id, [])) for e in active_employees],
        prepayment_enabled=getattr(biz, 'prepayment_enabled', False) or False,
        prepayment_percent=getattr(biz, 'prepayment_percent', None),
        payment_phone=getattr(biz, 'payment_phone', None),
        payment_details=getattr(biz, 'payment_details', None),
        cancellation_policy_photo=getattr(biz, 'cancellation_policy_photo', None),
        cancellation_policy_text=getattr(biz, 'cancellation_policy_text', None),
        require_receipt_for_prepayment=getattr(biz, 'require_receipt_for_prepayment', False) or False,
        booking_labels=_parse_booking_labels(getattr(biz, 'booking_labels', None)),
        booking_flow_order=(
            getattr(biz, 'booking_flow_order', 'service_first')
            if getattr(biz, 'booking_flow_order', 'service_first') in ("service_first", "resource_first")
            else "service_first"
        ),
    )


# ---------- GET /businesses/{id}/slots ----------

@router.get("/businesses/{business_id}/slots", response_model=List[SlotOut])
async def get_slots(
    business_id: int,
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    service_id: Optional[int] = Query(None),
    employee_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Available time slots for a given date.
    Algorithm matches the Telegram bot logic (client.py).
    """
    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # Determine interval
    interval = business.booking_interval_minutes or 30
    if employee_id:
        emp_result = await db.execute(select(Employee).where(Employee.id == employee_id))
        emp = emp_result.scalar_one_or_none()
        if emp and emp.booking_interval_minutes:
            interval = emp.booking_interval_minutes

    # Working hours
    start_time = business.working_hours_start or time(9, 0)
    end_time = business.working_hours_end or time(18, 0)

    # Fetch existing bookings for this date (all active statuses)
    booking_filter = [
        Booking.business_id == business_id,
        Booking.booking_date == date,
        Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
    ]
    if employee_id:
        booking_filter.append(Booking.employee_id == employee_id)

    existing = await db.execute(
        select(Booking.booking_time).where(and_(*booking_filter))
    )
    booked_times = {row[0] for row in existing.all()}

    # Generate slots
    current = datetime.combine(date, start_time)
    end_dt = datetime.combine(date, end_time)

    # Handle overnight hours (e.g. 09:00 — 02:00 means until 2 AM next day)
    if end_time <= start_time:
        end_dt += timedelta(days=1)

    # If today, start from now + 1 hour
    if date == datetime.now().date():
        now_plus = datetime.now() + timedelta(hours=1)
        if current < now_plus:
            current = now_plus
            # Round up to next interval
            minutes = (current.minute // interval + 1) * interval
            if minutes >= 60:
                current = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                current = current.replace(minute=minutes, second=0, microsecond=0)

    slots: List[SlotOut] = []
    while current <= end_dt:
        t = current.time()

        # Skip break
        is_break = False
        if business.break_start and business.break_end:
            if business.break_start <= t < business.break_end:
                is_break = True

        # Skip already booked
        if not is_break and t not in booked_times:
            slots.append(SlotOut(time=t.strftime("%H:%M")))

        current += timedelta(minutes=interval)

    return slots


# ---------- GET /businesses/{biz_id}/calculate-price ----------

@router.get("/businesses/{biz_id}/calculate-price", response_model=CalculatePriceOut)
async def calculate_price(
    biz_id: int,
    employee_id: int = Query(...),
    time: str = Query(..., description="Start time HH:MM"),
    duration: int = Query(..., description="Duration in minutes"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD for day_type filtering"),
    db: AsyncSession = Depends(get_db),
):
    """Calculate price based on venue time pricing rules."""
    # Fetch pricing rules for employee
    query = select(VenueTimePricing).where(VenueTimePricing.employee_id == employee_id)
    result = await db.execute(query)
    rules = result.scalars().all()

    if not rules:
        return CalculatePriceOut(has_time_price=False, total=0, segments=[])

    # Filter by day_type if date provided
    if date:
        from datetime import datetime as dt
        try:
            d = dt.strptime(date, "%Y-%m-%d").date()
            day_of_week = d.weekday()  # 0=Mon, 6=Sun
            is_weekend = day_of_week >= 5
            filtered = []
            for r in rules:
                if r.day_type == "all":
                    filtered.append(r)
                elif r.day_type == "weekday" and not is_weekend:
                    filtered.append(r)
                elif r.day_type == "weekend" and is_weekend:
                    filtered.append(r)
            if filtered:
                rules = filtered
        except (ValueError, AttributeError):
            pass  # If date parsing fails, use all rules

    time_str = time
    h, m = map(int, time_str.split(":"))
    start_min = h * 60 + m
    end_min = start_min + duration

    segments = []
    total = 0
    current = start_min

    while current < end_min:
        current_in_day = current % 1440
        matched_rule = None
        for r in rules:
            rf = r.time_from.hour * 60 + r.time_from.minute
            rt = r.time_to.hour * 60 + r.time_to.minute
            if rt <= rf:  # cross midnight (e.g. 00:00-09:00 means from 0:00 to 9:00)
                if current_in_day >= rf or current_in_day < rt:
                    matched_rule = r
                    break
            else:
                if rf <= current_in_day < rt:
                    matched_rule = r
                    break

        if not matched_rule:
            current += 1
            continue

        rf = matched_rule.time_from.hour * 60 + matched_rule.time_from.minute
        rt = matched_rule.time_to.hour * 60 + matched_rule.time_to.minute
        if rt <= rf:
            rt += 1440

        seg_end_limit = current + (rt - current_in_day) if current_in_day >= rf else current + (rt - current_in_day)
        seg_end = min(end_min, seg_end_limit)
        seg_minutes = seg_end - current
        subtotal = int(seg_minutes / 60 * matched_rule.price_per_hour)

        segments.append(PriceSegment(
            time_from=f"{(current % 1440) // 60:02d}:{(current % 1440) % 60:02d}",
            time_to=f"{(seg_end % 1440) // 60:02d}:{(seg_end % 1440) % 60:02d}",
            minutes=seg_minutes,
            price_per_hour=matched_rule.price_per_hour,
            subtotal=subtotal,
        ))
        total += subtotal
        current = seg_end

    return CalculatePriceOut(has_time_price=True, total=total, segments=segments)


# ---------- POST /bookings ----------

@router.post("/bookings", response_model=List[BookingOut])
async def create_booking(
    body: CreateBookingIn,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Create new booking(s). Supports multiple services with sequential times."""
    # Validate business
    biz_result = await db.execute(select(Business).where(Business.id == body.business_id))
    business = biz_result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # Resolve user: authenticated or find/create by phone
    booking_user = user
    if not booking_user:
        if not body.client_phone:
            raise HTTPException(status_code=401, detail="Authentication required or provide client_phone")
        # Find or create guest client by phone (гостевой профиль, привязан к телефону)
        booking_user = await get_or_create_guest_user(db, body.client_name or "Web Client", body.client_phone)

    # Determine service IDs list
    svc_ids = list(body.service_ids) if body.service_ids else []
    if not svc_ids and body.service_id:
        svc_ids = [body.service_id]
    if not svc_ids:
        raise HTTPException(status_code=400, detail="No service specified")

    # Validate the selected resource and its explicit service links. An employee/resource
    # with no links keeps the legacy "works with all services" behaviour.
    if body.employee_id:
        emp_result = await db.execute(
            select(Employee).where(
                Employee.id == body.employee_id,
                Employee.business_id == body.business_id,
                Employee.is_active == True,
            )
        )
        selected_employee = emp_result.scalar_one_or_none()
        if not selected_employee:
            raise HTTPException(status_code=404, detail="Employee/resource not found")
        links_result = await db.execute(
            select(EmployeeService.service_id).where(EmployeeService.employee_id == body.employee_id)
        )
        linked_service_ids = {row[0] for row in links_result.all()}
        incompatible = [service_id for service_id in svc_ids if linked_service_ids and service_id not in linked_service_ids]
        if incompatible:
            raise HTTPException(status_code=422, detail="Selected resource does not provide one or more selected services")

    # Parse start time
    try:
        booking_time = datetime.strptime(body.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format, expected HH:MM")

    # Повтор: тот же день недели/время, 2-8 повторов включая первый (без repeat_weeks — 1 дата, как раньше).
    occurrence_dates = compute_recurring_dates(body.date, body.repeat_weeks or 1)
    created_bookings = []

    # Pre-compute additional services info for notes
    addon_notes_parts = []
    addon_total_price = 0
    if body.additional_service_ids:
        for addon_id in body.additional_service_ids:
            addon_res = await db.execute(
                select(Service).where(Service.id == addon_id, Service.business_id == body.business_id)
            )
            addon_svc = addon_res.scalar_one_or_none()
            if addon_svc:
                hours = (body.additional_service_hours or {}).get(str(addon_id), 1)
                price = (addon_svc.price or 0) * hours
                addon_total_price += price
                addon_notes_parts.append(f"+ {addon_svc.name} ({price}₽)")

    # Build notes with addon info
    booking_notes = body.notes or ""
    if addon_notes_parts:
        if booking_notes:
            booking_notes += "\n"
        booking_notes += "Доп. услуги: " + ", ".join(addon_notes_parts)

    # Precompute prepayment amount for the visit (same services repeat on
    # every occurrence date if repeat_weeks is set — one amount applies to
    # every booking row created below, matching the pattern already used
    # in webapp/server.py::api_client_create_booking).
    visit_prepayment_amount = None
    if getattr(business, 'prepayment_enabled', False):
        main_services_result = await db.execute(
            select(Service).where(Service.id.in_(svc_ids), Service.business_id == body.business_id)
        )
        main_services_price_total = sum((s.price or 0) for s in main_services_result.scalars().all())
        visit_total_price = main_services_price_total + addon_total_price
        prepayment_percent = business.prepayment_percent or 100
        visit_prepayment_amount = int(visit_total_price * prepayment_percent / 100)

    # Phase 1: проверка конфликтов по ВСЕМ датам повтора, без записи в БД.
    # Атомарность: если конфликтует хоть одна дата — не создаём ничего.
    if len(occurrence_dates) > 1:
        conflicts = []
        for occ_date in occurrence_dates:
            check_time = datetime.combine(occ_date, booking_time)
            for svc_id in svc_ids:
                svc_result = await db.execute(
                    select(Service).where(
                        Service.id == svc_id,
                        Service.business_id == body.business_id,
                        Service.is_active == True,
                    )
                )
                service = svc_result.scalar_one_or_none()
                if not service:
                    raise HTTPException(status_code=404, detail=f"Service {svc_id} not found")
                bt = check_time.time()
                conflict_filter = [
                    Booking.business_id == body.business_id,
                    Booking.booking_date == occ_date,
                    Booking.booking_time == bt,
                    Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
                ]
                if body.employee_id:
                    conflict_filter.append(Booking.employee_id == body.employee_id)
                conflict_result = await db.execute(select(Booking).where(and_(*conflict_filter)))
                if conflict_result.scalar_one_or_none():
                    conflicts.append(f"{occ_date.strftime('%d.%m')} {bt.strftime('%H:%M')}")
                check_time += timedelta(minutes=service.duration_minutes or 30)
        if conflicts:
            raise HTTPException(status_code=409, detail="Занято: " + ", ".join(conflicts))

    # Phase 2: создание записей по каждой дате повтора.
    for occ_date in occurrence_dates:
        current_time = datetime.combine(occ_date, booking_time)
        for svc_id in svc_ids:
            # Validate service
            svc_result = await db.execute(
                select(Service).where(
                    Service.id == svc_id,
                    Service.business_id == body.business_id,
                    Service.is_active == True,
                )
            )
            service = svc_result.scalar_one_or_none()
            if not service:
                raise HTTPException(status_code=404, detail=f"Service {svc_id} not found")

            bt = current_time.time()

            # Check for conflicts with row locking to prevent race conditions
            conflict_filter = [
                Booking.business_id == body.business_id,
                Booking.booking_date == occ_date,
                Booking.booking_time == bt,
                Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
            ]
            if body.employee_id:
                conflict_filter.append(Booking.employee_id == body.employee_id)

            conflict_result = await db.execute(
                select(Booking).where(and_(*conflict_filter)).with_for_update(skip_locked=True)
            )
            if conflict_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"Time slot {bt.strftime('%H:%M')} is already taken",
                )

            # Use pending_prepayment status when prepayment is enabled (matches bot flow)
            initial_status = "pending_prepayment" if getattr(business, 'prepayment_enabled', False) else "pending"
            booking = Booking(
                business_id=body.business_id,
                client_id=booking_user.id,
                service_id=svc_id,
                employee_id=body.employee_id,
                booking_date=occ_date,
                booking_time=bt,
                status=initial_status,
                notes=booking_notes or None,
                notify_token=str(uuid.uuid4()),
                prepayment_amount=visit_prepayment_amount if initial_status == "pending_prepayment" else None,
            )
            db.add(booking)
            created_bookings.append(booking)

            # Advance time by service duration for sequential bookings
            current_time += timedelta(minutes=service.duration_minutes or 30)

    await db.commit()

    # Reload with relationships
    result_bookings = []
    for b in created_bookings:
        await db.refresh(b)
        full = await db.execute(
            select(Booking)
            .where(Booking.id == b.id)
            .options(
                selectinload(Booking.business),
                selectinload(Booking.service),
                selectinload(Booking.employee),
            )
        )
        loaded = full.scalar_one()
        can_c, can_r = _can_modify_booking(loaded)
        result_bookings.append(_booking_to_out(loaded, can_cancel=can_c, can_reschedule=can_r))

    # Fire-and-forget notifications — SAME format as bot (notifications.py)
    async def _send_booking_notifications():
        try:
            bot_token = "8334888136:AAGNj5q_5gChU63lU4kGMF5MPtbOV2WDM50"
            client_name = body.client_name or (booking_user.full_name if booking_user else "Клиент") or "Клиент"
            client_phone = body.client_phone or (booking_user.phone if booking_user else None)
            client_tg_id = booking_user.telegram_id if booking_user else None

            # Build client link (same as bot: tg://user?id=...)
            if client_tg_id and client_tg_id > 0:
                client_link = f'<a href="tg://user?id={client_tg_id}">{client_name}</a>'
            else:
                client_link = client_name

            # Format phone link (same as bot: format_phone + tel: link)
            phone_line = ""
            if client_phone:
                clean_phone = ''.join(c for c in client_phone if c.isdigit() or c == '+')
                if clean_phone.startswith('+'):
                    clean_digits = clean_phone[1:]
                else:
                    clean_digits = clean_phone
                if len(clean_digits) == 10:
                    formatted_phone = f"+7{clean_digits}"
                elif len(clean_digits) == 11 and clean_digits.startswith('7'):
                    formatted_phone = f"+7{clean_digits[1:]}"
                elif len(clean_digits) == 11 and clean_digits.startswith('8'):
                    formatted_phone = f"8{clean_digits[1:]}"
                else:
                    formatted_phone = client_phone
                tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
                phone_line = f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

            # Date formatting (same as bot: DD.MM.YYYY (Пн))
            weekdays_ru = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
            weekday = weekdays_ru[body.date.weekday()]
            booking_date_str = f"{body.date.strftime('%d.%m.%Y')} ({weekday})"

            # Collect services info — только по ПЕРВОМУ визиту серии: при повторе
            # result_bookings содержит len(occurrence_dates) * len(svc_ids) строк
            # (по одной на каждую услугу каждой недели), иначе уведомление показало бы
            # услуги/сумму/длительность, умноженные на количество повторов.
            first_visit_bookings = result_bookings[:len(svc_ids)] if svc_ids else result_bookings
            main_services = []
            for rb in first_visit_bookings:
                if rb.service_name:
                    main_services.append({
                        "name": rb.service_name,
                        "price": rb.service_price or 0,
                        "duration": rb.service_duration or 0,
                    })

            addon_services = []
            addon_total = 0
            if body.additional_service_ids:
                for addon_id in body.additional_service_ids:
                    addon_result = await db.execute(select(Service).where(Service.id == addon_id))
                    addon_svc = addon_result.scalar_one_or_none()
                    if addon_svc:
                        hours = (body.additional_service_hours or {}).get(str(addon_id), 1)
                        price = (addon_svc.price or 0) * hours
                        addon_total += price
                        addon_services.append({"name": addon_svc.name, "price": price, "duration": addon_svc.duration_minutes or 0})

            main_total = sum(s["price"] for s in main_services)
            grand_total = main_total + addon_total
            total_duration = sum(s["duration"] for s in main_services)
            first_time = result_bookings[0].time if result_bookings else body.time
            first_booking_id = created_bookings[0].id if created_bookings else None

            # Employee info
            emp = None
            emp_name = ""
            if body.employee_id:
                emp_result = await db.execute(select(Employee).where(Employee.id == body.employee_id))
                emp = emp_result.scalar_one_or_none()
                emp_name = emp.name if emp else ""

            # Employee label based on business type (same as bot)
            biz_type = business.business_type or "default"
            from bot.utils.business_types import get_terminology, is_venue_rental_type
            term = get_terminology(biz_type)
            emp_label = term.get("employee", "Мастер")
            is_venue = is_venue_rental_type(biz_type)

            # --- Build services text block (same format as bot) ---
            svc_lines = ""
            for s in main_services:
                price_part = f" - {s['price']}₽" if s['price'] else ""
                svc_lines += f"  • {s['name']}{price_part}\n"
            if addon_services:
                svc_lines += "\n  📎 Доп. услуги:\n"
                for a in addon_services:
                    price_part = f" - {a['price']}₽" if a['price'] else ""
                    svc_lines += f"  • {a['name']}{price_part}\n"

            # ── 1. OWNER notification (same as bot: notify_owner_new_booking) ──
            owner_msg = (
                f"\n🆕 <b>Новая запись в {business.name}</b>\n\n"
                f"📅 {booking_date_str} в {first_time}\n\n"
                f"👤 Клиент: {client_link}\n"
                f"{phone_line}"
                f"\n💼 Услуги:\n{svc_lines}"
            )
            if grand_total > 0:
                owner_msg += f"\n💰 Общая сумма: {grand_total}₽"
            if len(occurrence_dates) > 1:
                owner_msg += f"\n🔁 Повторится ещё {len(occurrence_dates) - 1} раз(а) — каждую неделю"
            if emp_name:
                if is_venue:
                    owner_msg += f"\n\n🏠 Помещение: {emp_name}"
                else:
                    owner_msg += f"\n\n👔 {emp_label}: {emp_name}"
            if body.notes:
                owner_msg += f"\n\n💬 Комментарий: {body.notes}"

            # Keyboard (same callback_data as bot: admin_kb.get_booking_admin_actions_keyboard)
            confirm_kb = None
            if first_booking_id:
                confirm_kb = {
                    "inline_keyboard": [
                        [{"text": "✅ Подтвердить", "callback_data": f"admin_confirm:{first_booking_id}"}],
                        [{"text": "✔️ Завершить", "callback_data": f"admin_complete:{first_booking_id}"}],
                        [{"text": "❌ Отменить", "callback_data": f"admin_cancel:{first_booking_id}"}]
                    ]
                }

            async with httpx.AsyncClient() as http:
                # Owner
                if business and business.owner_id:
                    owner_result = await db.execute(select(User).where(User.id == business.owner_id))
                    owner = owner_result.scalar_one_or_none()
                    if owner and owner.telegram_id:
                        payload = {"chat_id": owner.telegram_id, "text": owner_msg, "parse_mode": "HTML"}
                        if confirm_kb:
                            payload["reply_markup"] = confirm_kb
                        await http.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)

                # ── 2. MASTER notification (same as bot: notify_master_new_booking) ──
                if emp and getattr(emp, 'telegram_id', None):
                    master_msg = (
                        f"\n🆕 <b>Новая запись!</b>\n\n"
                        f"📅 Дата: {booking_date_str}\n"
                        f"🕐 Время: {first_time}\n\n"
                        f"👤 Клиент: {client_link}\n"
                        f"{phone_line}"
                        f"\n💼 Ваши услуги:\n{svc_lines}"
                        f"\n⏱ Длительность: {total_duration} мин"
                    )
                    if grand_total > 0:
                        master_msg += f"\n💰 Сумма: {grand_total}₽"
                    if body.notes:
                        master_msg += f"\n\n💬 Комментарий: {body.notes}"
                    await http.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": emp.telegram_id, "text": master_msg, "parse_mode": "HTML"},
                    )

                # ── 3. ADMINISTRATORS notification (same as bot: notify_administrator_new_booking) ──
                from datetime import date as date_cls
                if body.date == date_cls.today():
                    admins_result = await db.execute(
                        select(Employee).where(
                            Employee.business_id == body.business_id,
                            Employee.role.in_(["administrator", "master_and_admin"]),
                            Employee.telegram_id.isnot(None),
                            Employee.is_active == True,
                        )
                    )
                    admins = admins_result.scalars().all()
                    duty_admins = [a for a in admins if a.on_duty_date == date_cls.today()]
                    notify_admins = duty_admins if duty_admins else admins

                    admin_msg = (
                        f"\n🆕 <b>Новая запись в {business.name}</b>\n\n"
                        f"📅 {booking_date_str} в {first_time}\n\n"
                        f"👤 Клиент: {client_link}\n"
                        f"{phone_line}"
                        f"\n💼 Услуги:\n{svc_lines}"
                    )
                    if total_duration > 0:
                        admin_msg += f"\n⏱ Общая длительность: {total_duration} мин"
                    if grand_total > 0:
                        admin_msg += f"\n💰 Общая сумма: {grand_total}₽"
                    if emp_name:
                        if is_venue:
                            admin_msg += f"\n\n🏠 Помещение: {emp_name}"
                        else:
                            admin_msg += f"\n\n👔 {emp_label}: {emp_name}"
                    if body.notes:
                        admin_msg += f"\n\n💬 Комментарий: {body.notes}"

                    for adm in notify_admins:
                        if emp and adm.telegram_id == emp.telegram_id:
                            continue
                        try:
                            await http.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": adm.telegram_id, "text": admin_msg, "parse_mode": "HTML"},
                            )
                        except Exception:
                            pass

                # ── 4. CLIENT notification ──
                if booking_user and getattr(booking_user, 'telegram_id', None) and booking_user.telegram_id > 0:
                    from urllib.parse import quote
                    address_line = ""
                    if business.address:
                        encoded_addr = quote(business.address)
                        address_line = (
                            f'\n📍 <b>Адрес:</b> <a href="https://yandex.ru/maps/?text={encoded_addr}">{business.address}</a>'
                            f'\n🗺 <a href="https://yandex.ru/maps/?text={encoded_addr}">Яндекс.Карты</a>'
                            f' | <a href="https://2gis.ru/search/{encoded_addr}">2ГИС</a>'
                        )
                    biz_phone_line = ""
                    if business.phone:
                        biz_phone_line = f"\n📞 Телефон для связи: {business.phone}"

                    client_msg = (
                        f"✅ <b>Запись успешно создана!</b>\n\n"
                        f"🏢 {business.name}\n\n"
                        f"💼 Услуги:\n{svc_lines}"
                    )
                    if emp_name:
                        if is_venue:
                            client_msg += f"\n🏠 Помещение: {emp_name}"
                        else:
                            client_msg += f"\n👤 {emp_label}: {emp_name}"
                    client_msg += (
                        f"\n📅 Дата: {booking_date_str}\n"
                        f"🕐 Время: {first_time}"
                    )
                    if grand_total > 0:
                        client_msg += f"\n💰 Сумма: {grand_total}₽"
                    client_msg += f"{address_line}{biz_phone_line}"
                    client_msg += "\n\nЖдём вас! 🎉"
                    try:
                        await http.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": booking_user.telegram_id, "text": client_msg, "parse_mode": "HTML"},
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Booking notification error: {e}", exc_info=True)

    # Only send "Новая запись!" notification if NO prepayment required.
    # When prepayment is enabled, the bot's confirm_prepayment handler
    # (admin.py) sends all notifications after owner confirms payment.
    if not getattr(business, 'prepayment_enabled', False):
        asyncio.create_task(_send_booking_notifications())

    return result_bookings


# ---------- GET /my/bookings ----------

@router.get("/my/bookings", response_model=List[BookingOut])
async def my_bookings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's bookings (most recent first)."""
    result = await db.execute(
        select(Booking)
        .where(Booking.client_id == user.id)
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_date.desc(), Booking.booking_time.desc())
    )
    bookings = result.scalars().all()
    out = []
    for b in bookings:
        can_c, can_r = _can_modify_booking(b)
        out.append(_booking_to_out(b, can_cancel=can_c, can_reschedule=can_r))
    return out


# ---------- POST /bookings/{id}/cancel ----------

@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def cancel_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a booking (only the client who created it)."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.client_id != user.id:
        raise HTTPException(status_code=403, detail="Not your booking")
    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Already cancelled")

    booking.status = "cancelled"
    await db.commit()
    await db.refresh(booking)

    return _booking_to_out(booking)


# ---------- POST /bookings/{id}/reschedule ----------

@router.post("/bookings/{booking_id}/reschedule", response_model=List[BookingOut])
async def reschedule_booking(
    booking_id: int,
    body: RescheduleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reschedule a booking (and its group) to a new date/time."""
    # Load the target booking
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.client_id != user.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    can_c, can_r = _can_modify_booking(booking)
    if not can_r:
        raise HTTPException(status_code=400, detail="Cannot reschedule this booking")

    # Find booking group: same client, date, employee, consecutive times
    group_result = await db.execute(
        select(Booking)
        .where(
            Booking.client_id == user.id,
            Booking.booking_date == booking.booking_date,
            Booking.employee_id == booking.employee_id,
            Booking.status.in_(["pending", "confirmed"]),
        )
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_time.asc())
    )
    group_bookings = list(group_result.scalars().all())

    # Filter to consecutive bookings that include our target
    # Sort by time and find consecutive chain containing our booking
    sorted_bookings = sorted(group_bookings, key=lambda b: b.booking_time)
    chain = []
    found = False
    for i, b in enumerate(sorted_bookings):
        if b.id == booking_id:
            found = True
            # Walk back to find start of chain
            chain = [b]
            j = i - 1
            while j >= 0:
                prev = sorted_bookings[j]
                prev_svc = prev.service
                expected_end = datetime.combine(prev.booking_date, prev.booking_time) + timedelta(
                    minutes=prev_svc.duration_minutes if prev_svc else 30
                )
                if expected_end.time() == chain[0].booking_time:
                    chain.insert(0, prev)
                    j -= 1
                else:
                    break
            # Walk forward
            j = i + 1
            while j < len(sorted_bookings):
                nxt = sorted_bookings[j]
                last = chain[-1]
                last_svc = last.service
                expected_end = datetime.combine(last.booking_date, last.booking_time) + timedelta(
                    minutes=last_svc.duration_minutes if last_svc else 30
                )
                if expected_end.time() == nxt.booking_time:
                    chain.append(nxt)
                    j += 1
                else:
                    break
            break

    if not found:
        chain = [booking]

    # Parse new time
    try:
        new_time = datetime.strptime(body.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format, expected HH:MM")

    # Check new slots are available
    current_dt = datetime.combine(body.date, new_time)
    for b in chain:
        bt = current_dt.time()
        conflict_filter = [
            Booking.business_id == b.business_id,
            Booking.booking_date == body.date,
            Booking.booking_time == bt,
            Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
            Booking.id.notin_([x.id for x in chain]),
        ]
        if b.employee_id:
            conflict_filter.append(Booking.employee_id == b.employee_id)

        conflict_result = await db.execute(
            select(Booking).where(and_(*conflict_filter)).with_for_update(skip_locked=True)
        )
        if conflict_result.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Time slot {bt.strftime('%H:%M')} on {body.date} is already taken",
            )
        svc_dur = b.service.duration_minutes if b.service else 30
        current_dt += timedelta(minutes=svc_dur)

    # Update all bookings in chain
    current_dt = datetime.combine(body.date, new_time)
    for b in chain:
        b.booking_date = body.date
        b.booking_time = current_dt.time()
        # A moved visit needs fresh reminders for the new date/time.
        b.reminder_24h_sent = False
        b.reminder_2h_sent = False
        svc_dur = b.service.duration_minutes if b.service else 30
        current_dt += timedelta(minutes=svc_dur)

    await db.commit()

    # Reload and return
    result_bookings = []
    for b in chain:
        await db.refresh(b)
        full = await db.execute(
            select(Booking)
            .where(Booking.id == b.id)
            .options(
                selectinload(Booking.business),
                selectinload(Booking.service),
                selectinload(Booking.employee),
            )
        )
        loaded = full.scalar_one()
        can_c, can_r = _can_modify_booking(loaded)
        result_bookings.append(_booking_to_out(loaded, can_cancel=can_c, can_reschedule=can_r))

    return result_bookings


# ---------- GET /telegram-photo/{file_id:path} ----------

@router.get("/telegram-photo/{file_id:path}")
async def get_telegram_photo(file_id: str):
    """Proxy a Telegram photo by file_id — streams through server to hide bot token."""
    from fastapi.responses import StreamingResponse
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")

    async with create_photo_client() as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
        )
        data = resp.json()

    if not data.get("ok"):
        raise HTTPException(status_code=404, detail="Photo not found")

    file_path = data["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    # Stream the file through server instead of redirecting
    async def _stream():
        async with create_photo_client() as client:
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk

    content_type = "image/jpeg"
    if file_path.endswith(".png"):
        content_type = "image/png"
    elif file_path.endswith(".webp"):
        content_type = "image/webp"

    return StreamingResponse(
        _stream(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------- Shared prepayment/receipt logic (used by both id-based and token-based routes) ----------

async def _mark_prepayment_sent(booking: Booking, db: AsyncSession) -> dict:
    """Mark that the client has sent the prepayment and notify the owner."""
    booking.status = "prepayment_sent"
    await db.commit()

    # Notify owner — SAME format as bot (_build_prepayment_owner_text + get_booking_admin_actions_keyboard)
    try:
        business = booking.business
        if business and business.owner_id:
            owner_result = await db.execute(select(User).where(User.id == business.owner_id))
            owner = owner_result.scalar_one_or_none()
            if owner and owner.telegram_id:
                msg = await _build_prepayment_owner_msg(booking, db)
                prepay_kb = {
                    "inline_keyboard": [
                        [{"text": "✅ Подтвердить оплату", "callback_data": f"confirm_prepayment:{booking.id}"}],
                        [{"text": "❌ Отменить бронь / нет оплаты", "callback_data": f"reject_prepayment:{booking.id}"}]
                    ]
                }
                bot_token = "8334888136:AAGNj5q_5gChU63lU4kGMF5MPtbOV2WDM50"
                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": owner.telegram_id, "text": msg, "parse_mode": "HTML", "reply_markup": prepay_kb},
                    )
                    if resp.status_code != 200:
                        logger.error(f"Telegram sendMessage failed for prepayment booking {booking.id}: {resp.status_code} {resp.text}")
                    else:
                        logger.info(f"Prepayment notification sent to owner {owner.telegram_id} for booking {booking.id}")
            else:
                logger.warning(f"No owner telegram_id for booking {booking.id}")
        else:
            logger.warning(f"No business/owner for booking {booking.id}")
    except Exception as e:
        logger.error(f"Prepayment notification error for booking {booking.id}: {e}", exc_info=True)

    return {"message": "Payment notification recorded"}


async def _send_receipt_and_notify(booking: Booking, db: AsyncSession, file: UploadFile) -> dict:
    """Upload a receipt photo: forward it to the owner via Telegram and mark prepayment_sent."""
    booking.status = "prepayment_sent"
    await db.commit()

    # Send receipt to owner — same flow as bot:
    # 1. Send photo/document with short caption
    # 2. Send detailed text message with confirm/reject buttons
    try:
        business = booking.business
        if business and business.owner_id:
            owner_result = await db.execute(select(User).where(User.id == business.owner_id))
            owner = owner_result.scalar_one_or_none()
            if owner and owner.telegram_id:
                bot_token = "8334888136:AAGNj5q_5gChU63lU4kGMF5MPtbOV2WDM50"

                file_content = await file.read()
                content_type = file.content_type or "image/jpeg"
                filename = file.filename or "receipt.jpg"
                is_pdf = content_type == "application/pdf" or (filename and filename.lower().endswith(".pdf"))

                async with httpx.AsyncClient(timeout=30) as http:
                    # Step 1: send photo/document with short caption (same as bot)
                    photo_caption = "📸 Чек от клиента"
                    if is_pdf:
                        resp = await http.post(
                            f"https://api.telegram.org/bot{bot_token}/sendDocument",
                            data={"chat_id": str(owner.telegram_id), "caption": photo_caption},
                            files={"document": (filename, file_content, content_type)},
                        )
                    else:
                        resp = await http.post(
                            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                            data={"chat_id": str(owner.telegram_id), "caption": photo_caption},
                            files={"photo": (filename, file_content, content_type)},
                        )
                        if resp.status_code != 200:
                            logger.warning(f"sendPhoto failed for booking {booking.id}, trying sendDocument: {resp.text[:200]}")
                            resp = await http.post(
                                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                                data={"chat_id": str(owner.telegram_id), "caption": photo_caption},
                                files={"document": (filename, file_content, content_type)},
                            )
                    if resp.status_code != 200:
                        logger.error(f"Receipt photo send failed for booking {booking.id}: {resp.status_code} {resp.text}")

                    # Step 2: send detailed text with buttons (same format as bot)
                    msg = await _build_prepayment_owner_msg(
                        booking, db,
                        receipt_note="📸 <b>Клиент прикрепил чек (см. фото выше)</b>"
                    )
                    prepay_kb = {
                        "inline_keyboard": [
                            [{"text": "✅ Подтвердить оплату", "callback_data": f"confirm_prepayment:{booking.id}"}],
                            [{"text": "❌ Отменить бронь / нет оплаты", "callback_data": f"reject_prepayment:{booking.id}"}]
                        ]
                    }
                    resp2 = await http.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": owner.telegram_id, "text": msg, "parse_mode": "HTML", "reply_markup": prepay_kb},
                    )
                    if resp2.status_code != 200:
                        logger.error(f"Receipt text send failed for booking {booking.id}: {resp2.status_code} {resp2.text}")
                    else:
                        logger.info(f"Receipt notification sent to owner {owner.telegram_id} for booking {booking.id}")
            else:
                logger.warning(f"No owner telegram_id for receipt booking {booking.id}")
        else:
            logger.warning(f"No business/owner for receipt booking {booking.id}")

    except Exception as e:
        logger.error(f"Receipt notification error for booking {booking.id}: {e}", exc_info=True)

    return {"message": "Receipt uploaded and payment notification sent"}


def _booking_lookup_options():
    return (
        selectinload(Booking.client),
        selectinload(Booking.service),
        selectinload(Booking.employee),
        selectinload(Booking.business),
    )


# ---------- POST /bookings/{id}/prepayment-sent (authenticated) ----------

@router.post("/bookings/{booking_id}/prepayment-sent")
async def prepayment_sent(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Mark that the client has sent the prepayment and notify the owner."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(Booking).options(*_booking_lookup_options()).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.client_id != user.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    return await _mark_prepayment_sent(booking, db)


# ---------- POST /bookings/{id}/receipt (authenticated) ----------

@router.post("/bookings/{booking_id}/receipt")
async def upload_receipt(
    booking_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Upload a receipt photo: forward it to the owner via Telegram and mark prepayment_sent."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(Booking).options(*_booking_lookup_options()).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.client_id != user.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    return await _send_receipt_and_notify(booking, db, file)


# ---------- POST /bookings/by-token/{token}/prepayment-sent (QR/guest, no auth) ----------

@router.post("/bookings/by-token/{token}/prepayment-sent")
async def prepayment_sent_by_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Same as prepayment_sent, but for clients who booked without a Telegram login.

    Knowledge of the notify_token is itself the credential — no additional
    ownership check is needed or meaningful here.
    """
    result = await db.execute(
        select(Booking).options(*_booking_lookup_options()).where(Booking.notify_token == token)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    return await _mark_prepayment_sent(booking, db)


# ---------- POST /bookings/by-token/{token}/receipt (QR/guest, no auth) ----------

@router.post("/bookings/by-token/{token}/receipt")
async def upload_receipt_by_token(
    token: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Same as upload_receipt, but for clients who booked without a Telegram login."""
    result = await db.execute(
        select(Booking).options(*_booking_lookup_options()).where(Booking.notify_token == token)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    return await _send_receipt_and_notify(booking, db, file)


# ---------- GET /bookings/by-token/{token} (QR/guest, no auth) ----------


async def _find_visit_group(booking: Booking, db: AsyncSession) -> list:
    """Все брони того же визита: тот же клиент/бизнес/мастер/дата/время и
    текущий статус якорной брони (не только предоплатные — в отличие от
    _build_prepayment_owner_msg, который группирует только pending_prepayment
    + prepayment_sent, эта версия нужна и для confirmed/cancelled/completed)."""
    result = await db.execute(
        select(Booking).options(
            selectinload(Booking.service),
            selectinload(Booking.employee),
        ).where(
            Booking.client_id == booking.client_id,
            Booking.business_id == booking.business_id,
            Booking.employee_id == booking.employee_id,
            Booking.booking_date == booking.booking_date,
            Booking.booking_time == booking.booking_time,
            Booking.status == booking.status,
        )
    )
    group = list(result.scalars().all())
    return group or [booking]


@router.get("/bookings/by-token/{token}", response_model=PublicBookingOut)
async def get_booking_by_token(token: str, db: AsyncSession = Depends(get_db)):
    """Публичный статус брони по notify_token — без авторизации, без данных
    клиента. Используется гостевой страницей /b/:token."""
    result = await db.execute(
        select(Booking).options(*_booking_lookup_options()).where(Booking.notify_token == token)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    group = await _find_visit_group(booking, db)
    business = booking.business

    from bot.utils.business_types import get_terminology, is_venue_rental_type
    term = get_terminology(business.business_type)
    is_venue = is_venue_rental_type(business.business_type)

    services = [
        PublicServiceItem(
            name=b.service.name,
            price=b.service.price,
            is_additional=getattr(b.service, "is_additional", False),
        )
        for b in group if b.service
    ]
    total_price = sum(s.price or 0 for s in services)

    prepay_pct = business.prepayment_percent or 100
    computed_prepayment = booking.prepayment_amount or int(total_price * prepay_pct / 100)
    is_prepay_pending = booking.status in ("pending_prepayment", "prepayment_sent")

    return PublicBookingOut(
        notify_token=booking.notify_token,
        status=booking.status,
        business_name=business.name,
        business_address=business.address,
        business_phone=business.phone,
        business_directions=business.directions,
        date=booking.booking_date,
        time=booking.booking_time.strftime("%H:%M"),
        employee_name=booking.employee.name if booking.employee else None,
        employee_label="Помещение" if is_venue else term.get("employee", "Мастер"),
        services=services,
        total_price=total_price,
        prepayment_enabled=getattr(business, "prepayment_enabled", False) or False,
        prepayment_amount=computed_prepayment if is_prepay_pending else 0,
        payment_phone=business.payment_phone,
        payment_details=business.payment_details,
        require_receipt_for_prepayment=getattr(business, "require_receipt_for_prepayment", False) or False,
        cancellation_policy_text=getattr(business, "cancellation_policy_text", None),
        cancellation_policy_photo=getattr(business, "cancellation_policy_photo", None),
    )
