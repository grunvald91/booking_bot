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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..photo_transport import create_photo_client
from ..database import get_db, Business, Service, Employee, EmployeeService, Booking, User, VenueTimePricing
from ..deps import get_current_user, get_current_user_optional
from database.crud import get_or_create_guest_user
from database.booking_safety import (
    ACTIVE_BOOKING_STATUSES,
    BookingConflictError,
    booking_resource_duration,
    busy_resource_intervals,
    ensure_resource_available,
    lock_resource_days,
    service_occupies_resource,
    service_resource_duration,
)
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
        employee_id=b.employee_id,
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
    duration_minutes: Optional[int] = Query(None, ge=1, le=24 * 60),
    include_unavailable: bool = Query(False),
    exclude_booking_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Return candidate starts; optionally include busy starts as unavailable."""
    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    interval = business.booking_interval_minutes or 30
    if employee_id:
        emp_result = await db.execute(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.business_id == business_id,
                Employee.is_active.is_(True),
            )
        )
        emp = emp_result.scalar_one_or_none()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee/resource not found")
        if emp.booking_interval_minutes:
            interval = emp.booking_interval_minutes

    requested_duration = duration_minutes
    if requested_duration is None and service_id:
        service = (
            await db.execute(
                select(Service).where(
                    Service.id == service_id,
                    Service.business_id == business_id,
                    Service.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        requested_duration = service_resource_duration(service)
    requested_duration = requested_duration or interval

    start_time = business.working_hours_start or time(9, 0)
    end_time = business.working_hours_end or time(18, 0)
    current = datetime.combine(date, start_time)
    end_dt = datetime.combine(date, end_time)
    if end_time <= start_time:
        end_dt += timedelta(days=1)

    if date == datetime.now().date():
        now_plus = datetime.now() + timedelta(hours=1)
        if current < now_plus:
            current = now_plus
            minutes = (current.minute // interval + 1) * interval
            if minutes >= 60:
                current = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                current = current.replace(minute=minutes, second=0, microsecond=0)

    busy_intervals: list[tuple[datetime, datetime]] = []
    booked_times: set[time] = set()
    exclude_ids: list[int] = []
    if exclude_booking_id is not None:
        excluded = (
            await db.execute(
                select(Booking).where(
                    Booking.id == exclude_booking_id,
                    Booking.business_id == business_id,
                )
            )
        ).scalar_one_or_none()
        if excluded and (employee_id is None or excluded.employee_id == employee_id):
            exclude_ids = [excluded.id]

    if employee_id:
        busy_intervals = await busy_resource_intervals(
            db,
            employee_id=employee_id,
            dates=[date, end_dt.date()],
            exclude_booking_ids=exclude_ids,
        )
    else:
        existing = await db.execute(
            select(Booking.booking_time).where(
                Booking.business_id == business_id,
                Booking.booking_date == date,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            )
        )
        booked_times = {row[0] for row in existing.all()}

    slots: List[SlotOut] = []
    while current + timedelta(minutes=requested_duration) <= end_dt:
        t = current.time()
        candidate_end = current + timedelta(minutes=requested_duration)

        is_break = False
        if business.break_start and business.break_end:
            break_start = datetime.combine(current.date(), business.break_start)
            break_end = datetime.combine(current.date(), business.break_end)
            if break_end <= break_start:
                break_end += timedelta(days=1)
            is_break = current < break_end and break_start < candidate_end

        if employee_id:
            overlaps = any(
                current < busy_end and busy_start < candidate_end
                for busy_start, busy_end in busy_intervals
            )
        else:
            overlaps = t in booked_times

        available = not is_break and not overlaps
        if available or include_unavailable:
            slots.append(SlotOut(time=t.strftime("%H:%M"), available=available))

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
    """Create a complete visit atomically under one resource lock."""
    biz_result = await db.execute(select(Business).where(Business.id == body.business_id))
    business = biz_result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    booking_user = user
    if not booking_user:
        if not body.client_phone:
            raise HTTPException(status_code=401, detail="Authentication required or provide client_phone")
        booking_user = await get_or_create_guest_user(
            db,
            body.client_name or "Web Client",
            body.client_phone,
        )

    svc_ids = list(body.service_ids) if body.service_ids else []
    if not svc_ids and body.service_id:
        svc_ids = [body.service_id]
    if not svc_ids:
        raise HTTPException(status_code=400, detail="No service specified")
    if len(svc_ids) != len(set(svc_ids)):
        raise HTTPException(status_code=400, detail="Duplicate services are not allowed")

    services_result = await db.execute(
        select(Service).where(
            Service.id.in_(svc_ids),
            Service.business_id == body.business_id,
            Service.is_active.is_(True),
        )
    )
    service_map = {service.id: service for service in services_result.scalars().all()}
    missing_services = [service_id for service_id in svc_ids if service_id not in service_map]
    if missing_services:
        raise HTTPException(status_code=404, detail=f"Service {missing_services[0]} not found")
    main_services = [service_map[service_id] for service_id in svc_ids]
    if any(service.is_additional for service in main_services):
        raise HTTPException(status_code=400, detail="Additional service cannot be a main booking service")

    if body.employee_id:
        emp_result = await db.execute(
            select(Employee).where(
                Employee.id == body.employee_id,
                Employee.business_id == body.business_id,
                Employee.is_active.is_(True),
            )
        )
        selected_employee = emp_result.scalar_one_or_none()
        if not selected_employee:
            raise HTTPException(status_code=404, detail="Employee/resource not found")
        links_result = await db.execute(
            select(EmployeeService.service_id).where(EmployeeService.employee_id == body.employee_id)
        )
        linked_service_ids = {row[0] for row in links_result.all()}
        incompatible = [
            service_id
            for service_id in svc_ids
            if linked_service_ids and service_id not in linked_service_ids
        ]
        if incompatible:
            raise HTTPException(
                status_code=422,
                detail="Selected resource does not provide one or more selected services",
            )

    try:
        booking_time = datetime.strptime(body.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format, expected HH:MM")

    occurrence_dates = compute_recurring_dates(body.date, body.repeat_weeks or 1)
    created_bookings: list[Booking] = []

    addon_notes_parts: list[str] = []
    addon_total_price = 0
    addon_ids = list(body.additional_service_ids or [])
    if len(addon_ids) != len(set(addon_ids)):
        raise HTTPException(status_code=400, detail="Duplicate additional services are not allowed")
    if addon_ids:
        addon_result = await db.execute(
            select(Service).where(
                Service.id.in_(addon_ids),
                Service.business_id == body.business_id,
                Service.is_active.is_(True),
                Service.is_additional.is_(True),
            )
        )
        addon_map = {service.id: service for service in addon_result.scalars().all()}
        if len(addon_map) != len(addon_ids):
            raise HTTPException(status_code=400, detail="Additional service not found")
        for addon_id in addon_ids:
            addon_svc = addon_map[addon_id]
            hours = (body.additional_service_hours or {}).get(str(addon_id), 1)
            price = (addon_svc.price or 0) * hours
            addon_total_price += price
            addon_notes_parts.append(f"+ {addon_svc.name} ({price}₽)")

    booking_notes = body.notes or ""
    if addon_notes_parts:
        if booking_notes:
            booking_notes += "\n"
        booking_notes += "Доп. услуги: " + ", ".join(addon_notes_parts)

    visit_prepayment_amount = None
    if getattr(business, "prepayment_enabled", False):
        visit_total_price = sum((service.price or 0) for service in main_services) + addon_total_price
        prepayment_percent = business.prepayment_percent or 100
        visit_prepayment_amount = int(visit_total_price * prepayment_percent / 100)

    # One lock per resource/day window for the whole recurring series. The
    # second concurrent request waits here, then re-checks availability after
    # the first request commits.
    await lock_resource_days(db, body.employee_id, occurrence_dates)

    visit_duration = sum((service.duration_minutes or 30) for service in main_services)
    for occ_date in occurrence_dates:
        try:
            await ensure_resource_available(
                db,
                employee_id=body.employee_id,
                booking_date=occ_date,
                booking_time=booking_time,
                duration_minutes=visit_duration,
                acquire_lock=False,
            )
        except BookingConflictError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Занято: {occ_date.strftime('%d.%m')} {booking_time.strftime('%H:%M')}",
            ) from exc

    initial_status = (
        "pending_prepayment"
        if getattr(business, "prepayment_enabled", False)
        else "pending"
    )

    for occ_date in occurrence_dates:
        current_time = datetime.combine(occ_date, booking_time)
        for service in main_services:
            resource_duration = service.duration_minutes or 30
            booking = Booking(
                business_id=body.business_id,
                client_id=booking_user.id,
                service_id=service.id,
                employee_id=body.employee_id,
                booking_date=occ_date,
                booking_time=current_time.time(),
                status=initial_status,
                notes=booking_notes or None,
                notify_token=str(uuid.uuid4()),
                prepayment_amount=(
                    visit_prepayment_amount
                    if initial_status == "pending_prepayment"
                    else None
                ),
                resource_duration_minutes=resource_duration,
                occupies_resource=service_occupies_resource(service),
            )
            db.add(booking)
            created_bookings.append(booking)
            current_time += timedelta(minutes=resource_duration)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        message = str(exc).lower()
        if "bookings_no_active_resource_overlap" in message or "exclusion" in message:
            raise HTTPException(
                status_code=409,
                detail="Выбранное время только что занял другой клиент. Выберите другой слот.",
            ) from exc
        raise

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

    # A created booking without prepayment is immediately actionable and
    # therefore always notifies the client + all involved staff via every
    # available channel. This event is intentionally not configurable.
    if not getattr(business, "prepayment_enabled", False):
        try:
            from bot.services.booking_events import notify_booking_event
            first_visit_ids = [
                booking.id
                for booking in created_bookings[: max(1, len(main_services))]
                if booking.id
            ]
            await notify_booking_event(
                db,
                first_visit_ids,
                "created",
            )
        except Exception as notify_error:
            logger.error(
                "Immediate booking notification failed for business %s: %s",
                body.business_id,
                notify_error,
                exc_info=True,
            )

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

    try:
        from bot.services.booking_events import notify_booking_event
        await notify_booking_event(db, [booking.id], "cancelled")
    except Exception as notify_error:
        logger.error("Cancellation notification failed for booking %s: %s", booking.id, notify_error)

    return _booking_to_out(booking)


# ---------- POST /bookings/{id}/reschedule ----------

@router.post("/bookings/{booking_id}/reschedule", response_model=List[BookingOut])
async def reschedule_booking(
    booking_id: int,
    body: RescheduleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reschedule a visit atomically under the same resource lock as creation."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .with_for_update()
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.client_id != user.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    can_c, can_r = _can_modify_booking(booking)
    if not can_r:
        raise HTTPException(status_code=400, detail="Cannot reschedule this booking")

    group_result = await db.execute(
        select(Booking)
        .where(
            Booking.client_id == user.id,
            Booking.booking_date == booking.booking_date,
            Booking.employee_id == booking.employee_id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .options(
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_time.asc())
        .with_for_update()
    )
    group_bookings = list(group_result.scalars().all())

    sorted_bookings = sorted(group_bookings, key=lambda b: b.booking_time)
    chain: list[Booking] = []
    found = False
    for i, item in enumerate(sorted_bookings):
        if item.id != booking_id:
            continue
        found = True
        chain = [item]

        j = i - 1
        while j >= 0:
            prev = sorted_bookings[j]
            expected_end = datetime.combine(prev.booking_date, prev.booking_time) + timedelta(
                minutes=booking_resource_duration(prev)
            )
            if expected_end == datetime.combine(chain[0].booking_date, chain[0].booking_time):
                chain.insert(0, prev)
                j -= 1
            else:
                break

        j = i + 1
        while j < len(sorted_bookings):
            nxt = sorted_bookings[j]
            last = chain[-1]
            expected_end = datetime.combine(last.booking_date, last.booking_time) + timedelta(
                minutes=booking_resource_duration(last)
            )
            if expected_end == datetime.combine(nxt.booking_date, nxt.booking_time):
                chain.append(nxt)
                j += 1
            else:
                break
        break

    if not found:
        chain = [booking]

    try:
        new_time = datetime.strptime(body.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format, expected HH:MM")

    target_employee_id = booking.employee_id
    old_date = booking.booking_date
    old_time = booking.booking_time
    await lock_resource_days(db, target_employee_id, [old_date, body.date])

    visit_duration = sum(
        booking_resource_duration(item)
        for item in chain
        if getattr(item, "occupies_resource", True)
    )
    try:
        await ensure_resource_available(
            db,
            employee_id=target_employee_id,
            booking_date=body.date,
            booking_time=new_time,
            duration_minutes=visit_duration,
            exclude_booking_ids=[item.id for item in chain],
            acquire_lock=False,
        )
    except BookingConflictError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="На выбранное время уже есть другая запись",
        ) from exc

    current_dt = datetime.combine(body.date, new_time)
    for item in chain:
        item.booking_date = body.date
        item.booking_time = current_dt.time()
        item.reminder_24h_sent = False
        item.reminder_2h_sent = False
        item.staff_reminder_24h_sent = False
        item.staff_reminder_2h_sent = False
        current_dt += timedelta(minutes=booking_resource_duration(item))

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        message = str(exc).lower()
        if "bookings_no_active_resource_overlap" in message or "exclusion" in message:
            raise HTTPException(
                status_code=409,
                detail="На выбранное время уже есть другая запись",
            ) from exc
        raise

    result_bookings = []
    for item in chain:
        await db.refresh(item)
        full = await db.execute(
            select(Booking)
            .where(Booking.id == item.id)
            .options(
                selectinload(Booking.business),
                selectinload(Booking.service),
                selectinload(Booking.employee),
            )
        )
        loaded = full.scalar_one()
        can_c, can_r = _can_modify_booking(loaded)
        result_bookings.append(_booking_to_out(loaded, can_cancel=can_c, can_reschedule=can_r))

    try:
        from bot.services.booking_events import notify_booking_event
        await notify_booking_event(
            db,
            [item.id for item in chain],
            "rescheduled",
            old_date=old_date,
            old_time=old_time,
        )
    except Exception as notify_error:
        logger.error("Reschedule notification failed for booking %s: %s", booking_id, notify_error)

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
                bot_token = "***REMOVED***"
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
                bot_token = "***REMOVED***"

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
    prepayment_confirmed = booking.prepayment_confirmed_at is not None
    paid_amount = computed_prepayment if prepayment_confirmed else 0
    duration_minutes = sum(
        booking_resource_duration(item)
        for item in group
        if getattr(item, "occupies_resource", True)
    ) or booking_resource_duration(booking)

    return PublicBookingOut(
        notify_token=booking.notify_token,
        status=booking.status,
        business_name=business.name,
        business_address=business.address,
        business_phone=business.phone,
        business_directions=business.directions,
        date=booking.booking_date,
        time=booking.booking_time.strftime("%H:%M"),
        duration_minutes=duration_minutes,
        employee_name=booking.employee.name if booking.employee else None,
        employee_label="Помещение" if is_venue else term.get("employee", "Мастер"),
        services=services,
        total_price=total_price,
        prepayment_enabled=getattr(business, "prepayment_enabled", False) or False,
        prepayment_amount=computed_prepayment if getattr(business, "prepayment_enabled", False) else 0,
        paid_amount=paid_amount,
        prepayment_confirmed=prepayment_confirmed,
        payment_phone=business.payment_phone,
        payment_details=business.payment_details,
        require_receipt_for_prepayment=getattr(business, "require_receipt_for_prepayment", False) or False,
        cancellation_policy_text=getattr(business, "cancellation_policy_text", None),
        cancellation_policy_photo=getattr(business, "cancellation_policy_photo", None),
    )
