"""
Admin routes: dashboard, booking management, analytics.
All routes require the user to be a business owner.
"""
from datetime import date, datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from typing import List, Optional
import io
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from fastapi.responses import StreamingResponse
import json
import httpx
from sqlalchemy import select, func, and_, case, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..photo_transport import create_photo_client
from ..database import (
    get_db, Business, Service, Employee, Booking, User, BusinessOwner,
    VenueTimePricing, Subscription, SubscriptionService, EmployeeService,
)
from database.crud import get_or_create_guest_user
from ..deps import get_current_admin
from ..booking_utils import compute_recurring_dates
from ..schemas import (
    BusinessOut,
    BusinessUpdateIn,
    BusinessAdminDetailOut,
    DashboardOut,
    AdminBookingOut,
    ServiceOut,
    ServiceCreateIn,
    ServiceUpdateIn,
    ServiceReorderIn,
    EmployeeOut,
    EmployeeCreateIn,
    EmployeeUpdateIn,
    EmployeeServiceLinkIn,
    EmployeeServiceOut,
    AnalyticsPointOut,
    AnalyticsKPIs,
    AnalyticsTopItem,
    AnalyticsDailyPoint,
    AnalyticsPrepaymentStats,
    AnalyticsHeatmapCell,
    AnalyticsOverviewOut,
    ManualBookingIn,
    UpdateBookingStatusIn,
    AdminRescheduleIn,
    OwnerOut,
    OwnerAddIn,
    TimePricingCreateIn,
    TimePricingAdminOut,
    SubscriptionCreateIn,
    SubscriptionUpdateIn,
    SubscriptionAdminOut,
    SubscriptionServiceOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_owner_business_ids(
    db: AsyncSession, user: User
) -> List[int]:
    """Return all business IDs owned by the user (including co-ownership via BusinessOwner)."""
    # Legacy: Business.owner_id
    result1 = await db.execute(
        select(Business.id).where(Business.owner_id == user.id)
    )
    ids = {row[0] for row in result1.all()}
    # Junction table: BusinessOwner
    result2 = await db.execute(
        select(BusinessOwner.business_id).where(BusinessOwner.user_id == user.id)
    )
    ids.update(row[0] for row in result2.all())
    return list(ids)


def _admin_booking_out(b: Booking) -> AdminBookingOut:
    return AdminBookingOut(
        id=b.id,
        client_name=b.client.full_name if b.client else "Unknown",
        client_phone=b.client.phone if b.client else None,
        service_name=b.service.name if b.service else "",
        service_duration=b.duration_minutes or (b.service.duration_minutes if b.service else None),
        price=b.estimated_price if b.duration_minutes is not None else (b.service.price if b.service else None),
        is_rental=b.duration_minutes is not None,
        price_requires_confirmation=b.price_requires_confirmation,
        prepayment_amount=b.prepayment_amount,
        employee_name=b.employee.name if b.employee else None,
        employee_id=b.employee.id if b.employee else None,
        date=b.booking_date,
        time=b.booking_time.strftime("%H:%M"),
        status=b.status,
        notes=b.notes,
        created_at=b.created_at,
    )


def _service_out(service: Service) -> ServiceOut:
    """Convert Service model to ServiceOut, parsing group_pricing JSON."""
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


# ---------- GET /admin/dashboard ----------

@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Today's stats across all businesses owned by the user."""
    biz_ids = await _get_owner_business_ids(db, user)
    today = date.today()

    result = await db.execute(
        select(
            func.count(Booking.id),
            func.coalesce(
                func.sum(
                    case(
                        (Booking.status.in_(["confirmed", "completed"]), Service.price),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((Booking.status == "pending", 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Booking.status == "confirmed", 1), else_=0)), 0
            ),
        )
        .join(Service, Booking.service_id == Service.id)
        .where(
            Booking.business_id.in_(biz_ids),
            Booking.booking_date == today,
        )
    )
    row = result.one()

    return DashboardOut(
        today_bookings=row[0],
        total_revenue=row[1] or 0,
        pending_count=row[2] or 0,
        confirmed_count=row[3] or 0,
    )


# ---------- GET /admin/bookings ----------

@router.get("/bookings", response_model=List[AdminBookingOut])
async def list_bookings(
    date: Optional[date] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    business_id: Optional[int] = Query(None),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List bookings for the owner's businesses with optional filters."""
    biz_ids = await _get_owner_business_ids(db, user)

    if business_id:
        if business_id not in biz_ids:
            raise HTTPException(status_code=403, detail="Not your business")
        biz_ids = [business_id]

    filters = [Booking.business_id.in_(biz_ids)]
    if date:
        filters.append(Booking.booking_date == date)
    elif start_date and end_date:
        filters.append(Booking.booking_date >= start_date)
        filters.append(Booking.booking_date <= end_date)
    if status:
        filters.append(Booking.status == status)

    result = await db.execute(
        select(Booking)
        .where(and_(*filters))
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_date.desc(), Booking.booking_time.desc())
        .limit(200)
    )
    bookings = result.scalars().all()
    return [_admin_booking_out(b) for b in bookings]


# ---------- GET /admin/businesses/{id}/services ----------

@router.get("/businesses/{business_id}/services", response_model=List[ServiceOut])
async def list_services(
    business_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List services for a business owned by the current user."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Service).where(
            Service.business_id == business_id,
            Service.is_active == True,
        )
    )
    return [_service_out(s) for s in result.scalars().all()]


# ---------- GET /admin/businesses/{id}/employees ----------

@router.get("/businesses/{business_id}/employees", response_model=List[EmployeeOut])
async def list_employees(
    business_id: int,
    include_inactive: bool = Query(False),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List employees for a business owned by the current user."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    filters = [Employee.business_id == business_id]
    if not include_inactive:
        filters.append(Employee.is_active == True)

    result = await db.execute(
        select(Employee)
        .where(and_(*filters))
        .options(selectinload(Employee.employee_services))
    )
    employees = result.scalars().all()
    out = []
    for e in employees:
        d = EmployeeOut.model_validate(e)
        d.service_ids = [es.service_id for es in e.employee_services]
        out.append(d)
    return out


# ---------- GET /admin/analytics/{business_id} ----------

@router.get("/analytics/{business_id}", response_model=List[AnalyticsPointOut])
async def analytics(
    business_id: int,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Bookings per day for the last N days (default 30)."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    start_date = date.today() - timedelta(days=days)

    result = await db.execute(
        select(
            Booking.booking_date,
            func.count(Booking.id),
        )
        .where(
            Booking.business_id == business_id,
            Booking.booking_date >= start_date,
            Booking.status.in_(["confirmed", "completed"]),
        )
        .group_by(Booking.booking_date)
        .order_by(Booking.booking_date)
    )

    return [
        AnalyticsPointOut(date=row[0], count=row[1])
        for row in result.all()
    ]


# ---------- GET /admin/analytics/{business_id}/overview ----------

@router.get("/analytics/{business_id}/overview", response_model=AnalyticsOverviewOut)
async def analytics_overview(
    business_id: int,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """KPIs, top services/employees, daily breakdown, cancellations,
    prepayment conversion, and a fixed-90-day load heatmap."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    today = date.today()
    start_date = today - timedelta(days=days - 1)
    end_date = today
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    # ---- load business for working_hours ----
    biz_result = await db.execute(select(Business).where(Business.id == business_id))
    business = biz_result.scalar_one_or_none()

    # ---- helper: fetch bookings with service+employee for a date range, filtered by status ----
    async def _fetch_by_status(d_start: date, d_end: date, statuses: list[str]):
        res = await db.execute(
            select(Booking)
            .where(
                Booking.business_id == business_id,
                Booking.booking_date >= d_start,
                Booking.booking_date <= d_end,
                Booking.status.in_(statuses),
            )
            .options(selectinload(Booking.service), selectinload(Booking.employee))
        )
        return res.scalars().all()

    cur_bookings = await _fetch_by_status(start_date, end_date, ["confirmed", "completed"])
    prev_bookings = await _fetch_by_status(prev_start, prev_end, ["confirmed", "completed"])
    cur_cancelled = await _fetch_by_status(start_date, end_date, ["cancelled"])
    prev_cancelled = await _fetch_by_status(prev_start, prev_end, ["cancelled"])

    def _calc_revenue(bookings):
        total = 0
        for b in bookings:
            if b.service:
                total += b.service.price or 0
        return total

    def _calc_booked_minutes(bookings):
        total = 0
        for b in bookings:
            total += (b.service.duration_minutes if b.service else None) or 60
        return total

    cur_revenue = _calc_revenue(cur_bookings)
    cur_count = len(cur_bookings)
    cur_avg = round(cur_revenue / cur_count) if cur_count > 0 else 0

    prev_revenue = _calc_revenue(prev_bookings)
    prev_count = len(prev_bookings)
    prev_avg = round(prev_revenue / prev_count) if prev_count > 0 else 0

    def _cancellation_rate(cancelled_list, active_count):
        total = len(cancelled_list) + active_count
        return round(len(cancelled_list) / total * 100, 1) if total > 0 else 0.0

    cur_cancellation_rate = _cancellation_rate(cur_cancelled, cur_count)
    prev_cancellation_rate = _cancellation_rate(prev_cancelled, prev_count)

    # ---- load_percent ----
    # Fetch active employee count once
    emp_count_res = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.business_id == business_id,
            Employee.is_active == True,
        )
    )
    active_emp_count = emp_count_res.scalar() or 0

    def _load_percent(bookings, n_days):
        if (
            business is None
            or business.working_hours_start is None
            or business.working_hours_end is None
        ):
            return None
        wh_start = business.working_hours_start
        wh_end = business.working_hours_end
        working_hours = (
            wh_end.hour + wh_end.minute / 60.0
            - wh_start.hour - wh_start.minute / 60.0
        )
        if working_hours <= 0 or active_emp_count == 0:
            return None
        available_minutes = n_days * working_hours * active_emp_count * 60
        booked_minutes = _calc_booked_minutes(bookings)
        return round(booked_minutes / available_minutes * 100, 1)

    cur_load = _load_percent(cur_bookings, days)
    prev_load = _load_percent(prev_bookings, days)

    kpis = AnalyticsKPIs(
        revenue=cur_revenue,
        bookings=cur_count,
        avg_check=cur_avg,
        load_percent=cur_load,
        revenue_prev=prev_revenue,
        bookings_prev=prev_count,
        avg_check_prev=prev_avg,
        load_percent_prev=prev_load,
        cancellation_rate=cur_cancellation_rate,
        cancelled_count=len(cur_cancelled),
        cancellation_rate_prev=prev_cancellation_rate,
        cancelled_count_prev=len(prev_cancelled),
    )

    # ---- top services ----
    svc_map: dict[int, dict] = {}
    for b in cur_bookings:
        if b.service is None:
            continue
        sid = b.service.id
        if sid not in svc_map:
            svc_map[sid] = {"id": sid, "name": b.service.name, "count": 0, "revenue": 0}
        svc_map[sid]["count"] += 1
        svc_map[sid]["revenue"] += b.service.price or 0

    svc_list = sorted(
        svc_map.values(),
        key=lambda x: (x["revenue"], x["count"]),
        reverse=True,
    )[:5]
    top_services = [
        AnalyticsTopItem(
            id=s["id"],
            name=s["name"],
            count=s["count"],
            revenue=s["revenue"],
            share_percent=round(s["revenue"] / cur_revenue * 100, 1) if cur_revenue > 0 else 0.0,
        )
        for s in svc_list
    ]

    # ---- top employees ----
    emp_map: dict[int, dict] = {}
    for b in cur_bookings:
        if b.employee is None:
            continue
        eid = b.employee.id
        if eid not in emp_map:
            emp_map[eid] = {"id": eid, "name": b.employee.name, "count": 0, "revenue": 0}
        emp_map[eid]["count"] += 1
        if b.service:
            emp_map[eid]["revenue"] += b.service.price or 0

    emp_list = sorted(
        emp_map.values(),
        key=lambda x: (x["revenue"], x["count"]),
        reverse=True,
    )[:5]
    top_employees = [
        AnalyticsTopItem(
            id=e["id"],
            name=e["name"],
            count=e["count"],
            revenue=e["revenue"],
            share_percent=round(e["revenue"] / cur_revenue * 100, 1) if cur_revenue > 0 else 0.0,
        )
        for e in emp_list
    ]

    # ---- daily breakdown (bookings + revenue + cancelled) ----
    daily_map: dict[date, dict] = {}
    for b in cur_bookings:
        d = b.booking_date
        if d not in daily_map:
            daily_map[d] = {"bookings": 0, "revenue": 0, "cancelled": 0}
        daily_map[d]["bookings"] += 1
        if b.service:
            daily_map[d]["revenue"] += b.service.price or 0
    for b in cur_cancelled:
        d = b.booking_date
        if d not in daily_map:
            daily_map[d] = {"bookings": 0, "revenue": 0, "cancelled": 0}
        daily_map[d]["cancelled"] += 1

    daily = []
    current = start_date
    while current <= end_date:
        entry = daily_map.get(current, {"bookings": 0, "revenue": 0, "cancelled": 0})
        daily.append(AnalyticsDailyPoint(
            date=current, bookings=entry["bookings"], revenue=entry["revenue"], cancelled=entry["cancelled"],
        ))
        current += timedelta(days=1)

    # ---- prepayment conversion (current period, ALL statuses) ----
    all_period_bookings = await _fetch_by_status(
        start_date, end_date,
        ["pending", "confirmed", "completed", "cancelled", "pending_prepayment", "prepayment_sent"],
    )
    required = [b for b in all_period_bookings if b.prepayment_amount is not None]
    confirmed_pp = [b for b in required if b.prepayment_confirmed_at is not None]
    conversion_rate = round(len(confirmed_pp) / len(required) * 100, 1) if required else 0.0
    if confirmed_pp:
        total_minutes = sum(
            (b.prepayment_confirmed_at - b.created_at).total_seconds() / 60.0
            for b in confirmed_pp
            if b.created_at is not None
        )
        avg_confirmation_minutes = round(total_minutes / len(confirmed_pp), 1)
    else:
        avg_confirmation_minutes = None

    prepayment = AnalyticsPrepaymentStats(
        required_count=len(required),
        confirmed_count=len(confirmed_pp),
        conversion_rate=conversion_rate,
        avg_confirmation_minutes=avg_confirmation_minutes,
    )

    # ---- heatmap: fixed last 90 days, confirmed+completed only ----
    heatmap_start = today - timedelta(days=89)
    heatmap_bookings = await _fetch_by_status(heatmap_start, today, ["confirmed", "completed"])
    heatmap_map: dict[tuple[int, int], int] = {}
    for b in heatmap_bookings:
        dow = b.booking_date.weekday()
        hour = b.booking_time.hour
        key = (dow, hour)
        heatmap_map[key] = heatmap_map.get(key, 0) + 1
    heatmap = [
        AnalyticsHeatmapCell(day_of_week=dow, hour=hour, count=count)
        for (dow, hour), count in heatmap_map.items()
    ]

    return AnalyticsOverviewOut(
        kpis=kpis,
        top_services=top_services,
        top_employees=top_employees,
        daily=daily,
        prepayment=prepayment,
        heatmap=heatmap,
    )


# ---------- POST /admin/bookings (manual booking) ----------

@router.post("/bookings", response_model=List[AdminBookingOut])
async def create_manual_booking(
    data: ManualBookingIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a booking on behalf of a client (manual booking by owner).

    Поддерживает data.repeat_weeks (2-8) — еженедельный повтор. Атомарно:
    если конфликтует хоть одна из дат повтора, не создаётся ничего. Без
    repeat_weeks поведение не меняется (одна запись, без проверки конфликта —
    админ уже свёрился с расписанием визуально при клике по календарю)."""
    biz_ids = await _get_owner_business_ids(db, user)
    if data.business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    # Parse time
    from datetime import time as dt_time
    h, m = map(int, data.time.split(":"))
    booking_time = dt_time(h, m)

    occurrence_dates = compute_recurring_dates(data.date, data.repeat_weeks or 1)

    # Проверка конфликтов по всем датам ТОЛЬКО при повторе — за 8 недель вперёд
    # визуально свериться с расписанием нереально, в отличие от одиночного клика.
    if len(occurrence_dates) > 1:
        conflicts = []
        for occ_date in occurrence_dates:
            conflict_filter = [
                Booking.business_id == data.business_id,
                Booking.booking_date == occ_date,
                Booking.booking_time == booking_time,
                Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent"]),
            ]
            if data.employee_id:
                conflict_filter.append(Booking.employee_id == data.employee_id)
            conflict_result = await db.execute(select(Booking).where(and_(*conflict_filter)))
            if conflict_result.scalar_one_or_none():
                conflicts.append(f"{occ_date.strftime('%d.%m')} {data.time}")
        if conflicts:
            raise HTTPException(status_code=409, detail="Занято: " + ", ".join(conflicts))

    # Get or create a guest user for the client (один клиент на всю серию,
    # переиспользуется по телефону между визитами)
    guest_user = await get_or_create_guest_user(db, data.client_name, data.client_phone)

    created_ids = []
    for occ_date in occurrence_dates:
        booking = Booking(
            business_id=data.business_id,
            client_id=guest_user.id,
            service_id=data.service_id,
            employee_id=data.employee_id,
            booking_date=occ_date,
            booking_time=booking_time,
            status="confirmed",
            notes=data.notes,
            notify_token=str(uuid.uuid4()),
        )
        db.add(booking)
        await db.flush()
        created_ids.append(booking.id)

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(Booking)
        .where(Booking.id.in_(created_ids))
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_date)
    )
    bookings = result.scalars().all()
    return [_admin_booking_out(b) for b in bookings]


# ---------- PATCH /admin/bookings/{id}/status ----------

@router.patch("/bookings/{booking_id}/status", response_model=AdminBookingOut)
async def update_booking_status(
    booking_id: int,
    data: UpdateBookingStatusIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update booking status (confirm, complete, cancel)."""
    if data.status not in ("confirmed", "completed", "cancelled", "pending"):
        raise HTTPException(status_code=400, detail="Invalid status")

    biz_ids = await _get_owner_business_ids(db, user)

    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")
    if data.status == "confirmed" and booking.duration_minutes is not None and (
        booking.price_requires_confirmation or booking.prepayment_amount is None
    ):
        raise HTTPException(status_code=409, detail="Укажите окончательную цену и предоплату (0 ₽, если не требуется)")

    booking.status = data.status
    await db.commit()
    await db.refresh(booking)

    return _admin_booking_out(booking)


# ---------- POST /admin/bookings/{id}/reschedule ----------

@router.post("/bookings/{booking_id}/reschedule", response_model=AdminBookingOut)
async def admin_reschedule_booking(
    booking_id: int,
    data: AdminRescheduleIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Перенос записи владельцем/админом (drag&drop или кнопка «Перенести»)."""
    biz_ids = await _get_owner_business_ids(db, user)

    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")
    if booking.status not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail="Эту запись нельзя перенести")

    # Parse target slot
    try:
        h, m = map(int, data.time.split(":"))
        new_time = dt_time(h, m)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid time")

    duration = booking.duration_minutes or (booking.service.duration_minutes if booking.service else 30)
    slot_start = datetime.combine(data.date, new_time)
    slot_end = slot_start + timedelta(minutes=duration or 30)
    target_employee_id = data.employee_id if data.employee_id is not None else booking.employee_id
    if booking.duration_minutes is not None:
        if target_employee_id != booking.employee_id:
            raise HTTPException(status_code=400, detail="Для смены судна создайте новую заявку")
        business = await db.get(Business, booking.business_id)
        from web.api.rental_logic import available_starts
        if not business.working_hours_start or not business.working_hours_end:
            raise HTTPException(status_code=409, detail="Расписание не настроено")
        try:
            allowed = available_starts(data.date, business.working_hours_start,
                                       business.working_hours_end, duration, [],
                                       now=datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if data.time not in allowed:
            raise HTTPException(status_code=409, detail="Время вне рабочих часов или уже прошло")

    # Проверка пересечений с другими записями этого сотрудника
    if target_employee_id:
        result = await db.execute(
            select(Booking)
            .where(
                and_(
                    Booking.business_id == booking.business_id,
                    Booking.employee_id == target_employee_id,
                    Booking.booking_date == data.date,
                    Booking.status.in_(["pending", "confirmed", "pending_prepayment", "prepayment_sent", "prepayment_confirmed"]),
                    Booking.id != booking.id,
                )
            )
            .options(selectinload(Booking.service))
        )
        for eb in result.scalars().all():
            eb_start = datetime.combine(data.date, eb.booking_time)
            eb_dur = eb.duration_minutes or (eb.service.duration_minutes if eb.service else 30) or 30
            eb_end = eb_start + timedelta(minutes=eb_dur)
            if not (slot_end <= eb_start or slot_start >= eb_end):
                raise HTTPException(status_code=409, detail="На это время уже есть запись")

    booking.booking_date = data.date
    booking.booking_time = new_time
    # A moved visit needs fresh reminders for the new date/time.
    booking.reminder_24h_sent = False
    booking.reminder_2h_sent = False
    if data.employee_id is not None:
        booking.employee_id = target_employee_id
    await db.commit()

    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking.id)
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
    )
    booking = result.scalar_one()
    return _admin_booking_out(booking)


# ---------- GET /admin/businesses ----------

@router.get("/businesses", response_model=List[BusinessOut])
async def list_admin_businesses(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all businesses owned by the current admin."""
    biz_ids = await _get_owner_business_ids(db, user)
    result = await db.execute(
        select(Business).where(Business.id.in_(biz_ids))
    )
    businesses = result.scalars().all()
    return [
        BusinessOut(
            id=b.id, name=b.name, description=b.description,
            business_type=b.business_type, address=b.address, phone=b.phone,
            working_hours_start=b.working_hours_start, working_hours_end=b.working_hours_end,
            photos=b.photos, services_count=0,
        )
        for b in businesses
    ]


# ---------- Service CRUD ----------

@router.post("/businesses/{business_id}/services", response_model=ServiceOut)
async def create_service(
    business_id: int,
    data: ServiceCreateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    service = Service(
        business_id=business_id,
        name=data.name,
        description=data.description,
        duration_minutes=data.duration_minutes,
        price=data.price,
        is_active=data.is_active,
        is_additional=data.is_additional,
        is_hourly_price=data.is_hourly_price,
        pricing_type=data.pricing_type or 'fixed',
        group_pricing=json.dumps([t.model_dump() for t in data.group_pricing]) if data.group_pricing else None,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.put("/businesses/{business_id}/services/{service_id}", response_model=ServiceOut)
async def update_service(
    business_id: int,
    service_id: int,
    data: ServiceUpdateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Service).where(Service.id == service_id, Service.business_id == business_id)
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == 'group_pricing' and value is not None:
            setattr(service, field, json.dumps(value))
        else:
            setattr(service, field, value)

    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.delete("/businesses/{business_id}/services/{service_id}")
async def delete_service(
    business_id: int,
    service_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Service).where(Service.id == service_id, Service.business_id == business_id)
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    service.is_active = False
    await db.commit()
    return {"message": "Service deactivated"}


# ---------- Employee CRUD ----------

@router.post("/businesses/{business_id}/employees", response_model=EmployeeOut)
async def create_employee(
    business_id: int,
    data: EmployeeCreateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    employee = Employee(
        business_id=business_id,
        name=data.name,
        role=data.role,
        specialization=data.specialization,
        description=data.description,
        telegram_id=data.telegram_id,
        booking_interval_minutes=data.booking_interval_minutes,
        capacity=data.capacity,
        area_sqm=data.area_sqm,
        min_booking_minutes=data.min_booking_minutes,
        solo_price_per_hour=data.solo_price_per_hour,
        is_active=True,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return EmployeeOut.model_validate(employee)


@router.put("/businesses/{business_id}/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    business_id: int,
    employee_id: int,
    data: EmployeeUpdateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)

    await db.commit()
    await db.refresh(employee)
    return EmployeeOut.model_validate(employee)


@router.delete("/businesses/{business_id}/employees/{employee_id}")
async def delete_employee(
    business_id: int,
    employee_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    employee.is_active = False
    await db.commit()
    return {"message": "Employee deactivated"}


# ---------- Business Photo Management ----------

@router.post("/businesses/{business_id}/photo")
async def upload_business_photo(
    business_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Upload a photo for the business. Stores file_id via Telegram."""
    owner_biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in owner_biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")
    file_content = await file.read()
    content_type = file.content_type or "image/jpeg"
    filename = file.filename or "photo.jpg"

    # Upload to Telegram to get file_id (send to owner, then delete)
    chat_id = user.telegram_id if user.telegram_id and user.telegram_id > 0 else 437862772
    async with create_photo_client() as http:
        resp = await http.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={"chat_id": str(chat_id)},
            files={"photo": (filename, file_content, content_type)},
        )
        data = resp.json()

    if not data.get("ok"):
        raise HTTPException(status_code=500, detail="Failed to upload photo to Telegram")

    # Get the file_id and clean up the message
    msg_id = data["result"]["message_id"]
    photos_arr = data["result"]["photo"]
    file_id = photos_arr[-1]["file_id"]  # largest size

    # Delete the temp message
    async with create_photo_client() as http:
        await http.post(
            f"https://api.telegram.org/bot{bot_token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": msg_id},
        )

    # Update business photos JSON array
    existing_photos = []
    if business.photos:
        try:
            existing_photos = json.loads(business.photos)
        except (json.JSONDecodeError, TypeError):
            existing_photos = []

    existing_photos.append(file_id)
    business.photos = json.dumps(existing_photos)
    await db.commit()

    return {"file_id": file_id, "photos": existing_photos}


@router.delete("/businesses/{business_id}/photo/{photo_index}")
async def delete_business_photo(
    business_id: int,
    photo_index: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Delete a specific photo by index."""
    owner_biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in owner_biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    existing_photos = []
    if business.photos:
        try:
            existing_photos = json.loads(business.photos)
        except (json.JSONDecodeError, TypeError):
            existing_photos = []

    if photo_index < 0 or photo_index >= len(existing_photos):
        raise HTTPException(status_code=404, detail="Photo not found")

    existing_photos.pop(photo_index)
    business.photos = json.dumps(existing_photos) if existing_photos else None
    await db.commit()

    return {"photos": existing_photos}


# ---------- Employee Photo Management ----------

@router.post("/businesses/{business_id}/employees/{employee_id}/photo")
async def upload_employee_photo(
    business_id: int,
    employee_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Upload a photo for an employee/room. Stores file_id via Telegram."""
    owner_biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in owner_biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")
    file_content = await file.read()
    content_type = file.content_type or "image/jpeg"
    filename = file.filename or "photo.jpg"

    chat_id = user.telegram_id if user.telegram_id and user.telegram_id > 0 else 437862772
    async with create_photo_client() as http:
        resp = await http.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={"chat_id": str(chat_id)},
            files={"photo": (filename, file_content, content_type)},
        )
        data = resp.json()

    if not data.get("ok"):
        raise HTTPException(status_code=500, detail="Failed to upload photo to Telegram")

    msg_id = data["result"]["message_id"]
    photos_arr = data["result"]["photo"]
    file_id = photos_arr[-1]["file_id"]

    async with create_photo_client() as http:
        await http.post(
            f"https://api.telegram.org/bot{bot_token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": msg_id},
        )

    existing_photos = []
    if employee.photos:
        try:
            existing_photos = json.loads(employee.photos)
            if not isinstance(existing_photos, list):
                existing_photos = []
        except (json.JSONDecodeError, TypeError):
            existing_photos = []

    existing_photos.append(file_id)
    employee.photos = json.dumps(existing_photos)
    await db.commit()

    return {"file_id": file_id, "photos": existing_photos}


@router.delete("/businesses/{business_id}/employees/{employee_id}/photo/{photo_index}")
async def delete_employee_photo(
    business_id: int,
    employee_id: int,
    photo_index: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Delete a specific employee photo by index."""
    owner_biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in owner_biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    existing_photos = []
    if employee.photos:
        try:
            existing_photos = json.loads(employee.photos)
            if not isinstance(existing_photos, list):
                existing_photos = []
        except (json.JSONDecodeError, TypeError):
            existing_photos = []

    if photo_index < 0 or photo_index >= len(existing_photos):
        raise HTTPException(status_code=404, detail="Photo not found")

    existing_photos.pop(photo_index)
    employee.photos = json.dumps(existing_photos) if existing_photos else None
    await db.commit()

    return {"photos": existing_photos}


# ---------- GET /admin/businesses/{id}/detail ----------

@router.get("/businesses/{business_id}/detail", response_model=BusinessAdminDetailOut)
async def get_business_detail(
    business_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full business details for admin editing."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    return BusinessAdminDetailOut.model_validate(business)


# ---------- PUT /admin/businesses/{id} ----------

@router.put("/businesses/{business_id}", response_model=BusinessAdminDetailOut)
async def update_business(
    business_id: int,
    data: BusinessUpdateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update business profile and prepayment settings."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    updates = data.model_dump(exclude_unset=True)
    # Convert time strings to time objects. Accept both "HH:MM" and "HH:MM:SS"
    # (the API serializes Time columns as "HH:MM:SS", and an unedited <input type="time">
    # round-trips that exact string back to us).
    for time_field in ("working_hours_start", "working_hours_end", "break_start", "break_end"):
        if time_field in updates:
            val = updates[time_field]
            if val:
                parts = val.split(":")
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                updates[time_field] = dt_time(h, m)
            else:
                updates[time_field] = None

    for field, value in updates.items():
        setattr(business, field, value)

    await db.commit()
    await db.refresh(business)
    return BusinessAdminDetailOut.model_validate(business)


# ---------- Service Reorder ----------

@router.post("/businesses/{business_id}/services/reorder")
async def reorder_services(
    business_id: int,
    data: ServiceReorderIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reorder services by providing ordered list of service IDs."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Service).where(Service.business_id == business_id)
    )
    services = {s.id: s for s in result.scalars().all()}

    for idx, sid in enumerate(data.service_ids):
        if sid in services:
            services[sid].sort_order = idx

    await db.commit()
    return {"message": "Reordered"}


# ---------- Employee-Service Links ----------

@router.get("/businesses/{business_id}/employees/{employee_id}/services")
async def get_employee_services(
    business_id: int,
    employee_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get services linked to an employee."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(EmployeeService).join(Employee, EmployeeService.employee_id == Employee.id)
        .where(
            EmployeeService.employee_id == employee_id,
            Employee.business_id == business_id,
        )
        .options(selectinload(EmployeeService.service))
    )
    links = result.scalars().all()
    return [
        EmployeeServiceOut(service_id=es.service_id, service_name=es.service.name)
        for es in links if es.service
    ]


@router.put("/businesses/{business_id}/employees/{employee_id}/services")
async def set_employee_services(
    business_id: int,
    employee_id: int,
    data: EmployeeServiceLinkIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set services for an employee (replaces existing links)."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    # Verify employee belongs to business
    emp_result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    if not emp_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Employee not found")

    # Delete existing links
    await db.execute(
        sa_delete(EmployeeService).where(EmployeeService.employee_id == employee_id)
    )

    # Create new links
    for sid in data.service_ids:
        db.add(EmployeeService(employee_id=employee_id, service_id=sid))

    await db.commit()
    return {"message": "Services updated"}


# ---------- Venue Time Pricing ----------

@router.get("/businesses/{business_id}/employees/{employee_id}/time-pricing", response_model=List[TimePricingAdminOut])
async def get_time_pricing(
    business_id: int,
    employee_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(VenueTimePricing).join(Employee, VenueTimePricing.employee_id == Employee.id)
        .where(
            VenueTimePricing.employee_id == employee_id,
            Employee.business_id == business_id,
        )
    )
    return [
        TimePricingAdminOut(
            id=tp.id,
            time_from=tp.time_from.strftime("%H:%M"),
            time_to=tp.time_to.strftime("%H:%M"),
            price_per_hour=tp.price_per_hour,
            day_type=tp.day_type,
        )
        for tp in result.scalars().all()
    ]


@router.post("/businesses/{business_id}/employees/{employee_id}/time-pricing", response_model=TimePricingAdminOut)
async def add_time_pricing(
    business_id: int,
    employee_id: int,
    data: TimePricingCreateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    emp_result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    if not emp_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Employee not found")

    h1, m1 = map(int, data.time_from.split(":"))
    h2, m2 = map(int, data.time_to.split(":"))

    tp = VenueTimePricing(
        employee_id=employee_id,
        time_from=dt_time(h1, m1),
        time_to=dt_time(h2, m2),
        price_per_hour=data.price_per_hour,
        day_type=data.day_type,
    )
    db.add(tp)
    await db.commit()
    await db.refresh(tp)

    return TimePricingAdminOut(
        id=tp.id,
        time_from=tp.time_from.strftime("%H:%M"),
        time_to=tp.time_to.strftime("%H:%M"),
        price_per_hour=tp.price_per_hour,
        day_type=tp.day_type,
    )


@router.delete("/businesses/{business_id}/employees/{employee_id}/time-pricing/{pricing_id}")
async def delete_time_pricing(
    business_id: int,
    employee_id: int,
    pricing_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(VenueTimePricing).join(Employee, VenueTimePricing.employee_id == Employee.id)
        .where(
            VenueTimePricing.id == pricing_id,
            VenueTimePricing.employee_id == employee_id,
            Employee.business_id == business_id,
        )
    )
    tp = result.scalar_one_or_none()
    if not tp:
        raise HTTPException(status_code=404, detail="Pricing not found")

    await db.delete(tp)
    await db.commit()
    return {"message": "Deleted"}


# ---------- Duty Toggle ----------

@router.post("/businesses/{business_id}/employees/{employee_id}/toggle-duty")
async def toggle_duty(
    business_id: int,
    employee_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle employee on-duty status for today."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    today = date.today()
    if emp.on_duty_date == today:
        emp.on_duty_date = None
        on_duty = False
    else:
        emp.on_duty_date = today
        on_duty = True

    await db.commit()
    return {"on_duty": on_duty, "date": str(today)}


@router.get("/businesses/{business_id}/employees/{employee_id}/duty-schedule")
async def get_duty_schedule(
    business_id: int,
    employee_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get duty schedule (list of dates) for an employee."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    schedule = []
    raw = getattr(emp, 'duty_schedule', None)
    if raw:
        try:
            schedule = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {"dates": schedule}


@router.put("/businesses/{business_id}/employees/{employee_id}/duty-schedule")
async def set_duty_schedule(
    business_id: int,
    employee_id: int,
    data: dict,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set duty schedule (list of date strings) for an employee."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.business_id == business_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    dates = data.get("dates", [])
    # Validate date format
    valid_dates = []
    for d in dates:
        try:
            date.fromisoformat(str(d))
            valid_dates.append(str(d))
        except (ValueError, TypeError):
            pass

    emp.duty_schedule = json.dumps(valid_dates) if valid_dates else None
    await db.commit()
    return {"dates": valid_dates}


# ---------- Co-Owners ----------

@router.get("/businesses/{business_id}/owners", response_model=List[OwnerOut])
async def list_owners(
    business_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(BusinessOwner)
        .where(BusinessOwner.business_id == business_id)
        .options(selectinload(BusinessOwner.user))
    )
    owners = result.scalars().all()
    out = []
    for o in owners:
        out.append(OwnerOut(
            id=o.id,
            user_id=o.user_id,
            role=o.role,
            user_name=o.user.full_name if o.user else "Unknown",
            user_phone=o.user.phone if o.user else None,
            telegram_id=o.user.telegram_id if o.user else None,
            added_at=o.added_at,
        ))

    # Also include legacy owner_id if not already in BusinessOwner
    biz_result = await db.execute(select(Business).where(Business.id == business_id))
    biz = biz_result.scalar_one_or_none()
    if biz:
        owner_user_ids = {o.user_id for o in owners}
        if biz.owner_id not in owner_user_ids:
            owner_user_result = await db.execute(select(User).where(User.id == biz.owner_id))
            owner_user = owner_user_result.scalar_one_or_none()
            if owner_user:
                out.insert(0, OwnerOut(
                    id=0,
                    user_id=owner_user.id,
                    role="owner",
                    user_name=owner_user.full_name,
                    user_phone=owner_user.phone,
                    telegram_id=owner_user.telegram_id,
                    added_at=biz.created_at,
                ))

    return out


@router.post("/businesses/{business_id}/owners", response_model=OwnerOut)
async def add_owner(
    business_id: int,
    data: OwnerAddIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    # Find user by telegram_id or username
    if data.telegram_id:
        result = await db.execute(select(User).where(User.telegram_id == data.telegram_id))
    elif data.username:
        uname = data.username.lstrip("@")
        result = await db.execute(select(User).where(User.username == uname))
    else:
        raise HTTPException(status_code=400, detail="Provide telegram_id or username")

    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found (they must first start the bot)")

    # Check not already owner
    existing = await db.execute(
        select(BusinessOwner).where(
            BusinessOwner.business_id == business_id,
            BusinessOwner.user_id == target_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already an owner")

    owner = BusinessOwner(
        business_id=business_id,
        user_id=target_user.id,
        role="co_owner",
        added_by_id=user.id,
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    return OwnerOut(
        id=owner.id,
        user_id=target_user.id,
        role=owner.role,
        user_name=target_user.full_name,
        user_phone=target_user.phone,
        telegram_id=target_user.telegram_id,
        added_at=owner.added_at,
    )


@router.delete("/businesses/{business_id}/owners/{owner_id}")
async def remove_owner(
    business_id: int,
    owner_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(BusinessOwner).where(
            BusinessOwner.id == owner_id,
            BusinessOwner.business_id == business_id,
        )
    )
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    await db.delete(owner)
    await db.commit()
    return {"message": "Owner removed"}


# ---------- Subscription CRUD ----------

@router.get("/businesses/{business_id}/subscriptions", response_model=List[SubscriptionAdminOut])
async def list_subscriptions(
    business_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Subscription)
        .where(Subscription.business_id == business_id)
        .options(selectinload(Subscription.services).selectinload(SubscriptionService.service))
    )
    subs = result.scalars().all()
    out = []
    for s in subs:
        services = []
        for ss in s.services:
            if ss.service:
                services.append(SubscriptionServiceOut(
                    id=ss.service.id,
                    name=ss.service.name,
                    quantity=ss.quantity,
                ))
        out.append(SubscriptionAdminOut(
            id=s.id,
            name=s.name,
            description=s.description,
            price=s.price,
            validity_days=s.validity_days,
            rules=s.rules,
            is_active=s.is_active,
            services=services,
        ))
    return out


@router.post("/businesses/{business_id}/subscriptions", response_model=SubscriptionAdminOut)
async def create_subscription(
    business_id: int,
    data: SubscriptionCreateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    sub = Subscription(
        business_id=business_id,
        name=data.name,
        description=data.description,
        price=data.price,
        validity_days=data.validity_days,
        rules=data.rules,
    )
    db.add(sub)
    await db.flush()

    for svc in data.services:
        db.add(SubscriptionService(
            subscription_id=sub.id,
            service_id=svc.service_id,
            quantity=svc.quantity,
        ))

    await db.commit()

    # Reload with services
    result = await db.execute(
        select(Subscription)
        .where(Subscription.id == sub.id)
        .options(selectinload(Subscription.services).selectinload(SubscriptionService.service))
    )
    sub = result.scalar_one()
    services = []
    for ss in sub.services:
        if ss.service:
            services.append(SubscriptionServiceOut(
                id=ss.service.id, name=ss.service.name, quantity=ss.quantity,
            ))
    return SubscriptionAdminOut(
        id=sub.id, name=sub.name, description=sub.description,
        price=sub.price, validity_days=sub.validity_days, rules=sub.rules,
        is_active=sub.is_active, services=services,
    )


@router.put("/businesses/{business_id}/subscriptions/{subscription_id}", response_model=SubscriptionAdminOut)
async def update_subscription(
    business_id: int,
    subscription_id: int,
    data: SubscriptionUpdateIn,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.business_id == business_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    updates = data.model_dump(exclude_unset=True)
    services_data = updates.pop("services", None)

    for field, value in updates.items():
        setattr(sub, field, value)

    if services_data is not None:
        # Replace subscription services
        await db.execute(
            sa_delete(SubscriptionService).where(SubscriptionService.subscription_id == sub.id)
        )
        for svc in services_data:
            db.add(SubscriptionService(
                subscription_id=sub.id,
                service_id=svc["service_id"],
                quantity=svc.get("quantity", 1),
            ))

    await db.commit()

    # Reload
    result = await db.execute(
        select(Subscription)
        .where(Subscription.id == sub.id)
        .options(selectinload(Subscription.services).selectinload(SubscriptionService.service))
    )
    sub = result.scalar_one()
    services = []
    for ss in sub.services:
        if ss.service:
            services.append(SubscriptionServiceOut(
                id=ss.service.id, name=ss.service.name, quantity=ss.quantity,
            ))
    return SubscriptionAdminOut(
        id=sub.id, name=sub.name, description=sub.description,
        price=sub.price, validity_days=sub.validity_days, rules=sub.rules,
        is_active=sub.is_active, services=services,
    )


@router.delete("/businesses/{business_id}/subscriptions/{subscription_id}")
async def delete_subscription(
    business_id: int,
    subscription_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.business_id == business_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.is_active = False
    await db.commit()
    return {"message": "Subscription deactivated"}


# ---------- QR Code Generation ----------

@router.get("/businesses/{business_id}/qr")
async def generate_qr(
    business_id: int,
    target: str = Query("webapp", pattern="^(webapp|telegram)$"),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate QR code for booking (webapp or telegram link)."""
    biz_ids = await _get_owner_business_ids(db, user)
    if business_id not in biz_ids:
        raise HTTPException(status_code=403, detail="Not your business")

    try:
        import qrcode
    except ImportError:
        raise HTTPException(status_code=501, detail="qrcode library not installed")

    bot_username = "Sochiservice_bot"
    import os
    webapp_url = os.getenv("WEBAPP_URL", "https://booking.sochi-service.com")

    if target == "telegram":
        url = f"https://t.me/{bot_username}?start=book_{business_id}"
    else:
        url = f"{webapp_url}/book/{business_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png", headers={
        "Content-Disposition": f"inline; filename=qr_{target}_{business_id}.png",
        "X-QR-URL": url,
    })
