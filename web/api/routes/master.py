"""Личный кабинет мастера: только его собственные записи, без цен, аналитики и настроек.

Кто считается мастером этого человека (человек вошёл любым способом: Telegram, email или Яндекс ID):
  * Telegram: Telegram ID сотрудника совпадает с Telegram ID вошедшего;
  * email / Яндекс: подтверждённый email вошедшего (email-пароль или адрес из Яндекс ID)
    совпадает с «email для входа», который владелец указал в карточке сотрудника.
Непроверенные адреса (контактный email профиля) доступа не дают.
"""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Booking, Business, Employee, EmployeeDayOff, EmailIdentity, User, YandexIdentity,
)

from ..database import get_db
from ..deps import get_current_user

router = APIRouter()

MAX_RANGE_DAYS = 62


class MasterEmployeeOut(BaseModel):
    employee_id: int
    employee_name: str
    business_id: int
    business_name: str


class MasterMeOut(BaseModel):
    employees: List[MasterEmployeeOut] = []


class MasterBookingOut(BaseModel):
    id: int
    business_id: int
    business_name: str
    employee_id: int
    employee_name: str
    service_name: str
    duration_minutes: Optional[int] = None
    date: date
    time: str
    status: str
    client_name: str
    client_phone: Optional[str] = None
    notes: Optional[str] = None


class MasterDayOffOut(BaseModel):
    employee_id: int
    date: date


class MasterScheduleOut(BaseModel):
    date_from: date
    date_to: date
    employees: List[MasterEmployeeOut] = []
    bookings: List[MasterBookingOut] = []
    days_off: List[MasterDayOffOut] = []


async def verified_emails(db: AsyncSession, user: User) -> set[str]:
    """Адреса, которые этот человек подтвердил сам: пароль по email и email из Яндекс ID."""
    emails: set[str] = set()
    own = await db.scalar(select(EmailIdentity.email).where(EmailIdentity.user_id == user.id))
    if own:
        emails.add(own.strip().lower())
    yandex = await db.scalar(select(YandexIdentity.email).where(YandexIdentity.user_id == user.id))
    if yandex:
        emails.add(yandex.strip().lower())
    return emails


async def master_employees(db: AsyncSession, user: User) -> list[Employee]:
    """Активные сотрудники, под которых этот человек может войти."""
    conditions = []
    if user.telegram_id and user.telegram_id > 0:
        conditions.append(Employee.telegram_id == user.telegram_id)
    emails = await verified_emails(db, user)
    if emails:
        conditions.append(Employee.access_email.in_(emails))
    if not conditions:
        return []
    from sqlalchemy import or_
    result = await db.execute(
        select(Employee)
        .where(Employee.is_active.is_(True), or_(*conditions))
        .options(selectinload(Employee.business))
        .order_by(Employee.business_id, Employee.id)
    )
    return list(result.scalars().all())


def _employee_out(employee: Employee) -> MasterEmployeeOut:
    business: Business = employee.business
    return MasterEmployeeOut(
        employee_id=employee.id,
        employee_name=employee.name,
        business_id=employee.business_id,
        business_name=business.name if business else "",
    )


@router.get("/me", response_model=MasterMeOut)
async def master_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Есть ли у вошедшего человека кабинет мастера (нужно сайту, чтобы показать нужную страницу)."""
    return MasterMeOut(employees=[_employee_out(e) for e in await master_employees(db, user)])


@router.get("/schedule", response_model=MasterScheduleOut)
async def master_schedule(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Собственные записи мастера и его выходные за период (по умолчанию сегодня и 13 дней вперёд)."""
    employees = await master_employees(db, user)
    if not employees:
        raise HTTPException(status_code=403, detail="Для вас не открыт кабинет мастера")

    start = date_from or date.today()
    end = date_to or (start + timedelta(days=13))
    if end < start:
        raise HTTPException(status_code=422, detail="Конец периода раньше начала")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Период не больше {MAX_RANGE_DAYS} дней")

    employee_ids = [e.id for e in employees]
    bookings = (await db.execute(
        select(Booking)
        .where(
            Booking.employee_id.in_(employee_ids),
            Booking.booking_date >= start,
            Booking.booking_date <= end,
        )
        .options(selectinload(Booking.client), selectinload(Booking.service))
        .order_by(Booking.booking_date, Booking.booking_time)
    )).scalars().all()
    by_id = {e.id: e for e in employees}

    days_off = (await db.execute(
        select(EmployeeDayOff)
        .where(
            EmployeeDayOff.employee_id.in_(employee_ids),
            EmployeeDayOff.date >= start,
            EmployeeDayOff.date <= end,
        )
        .order_by(EmployeeDayOff.date)
    )).scalars().all()

    return MasterScheduleOut(
        date_from=start,
        date_to=end,
        employees=[_employee_out(e) for e in employees],
        bookings=[
            MasterBookingOut(
                id=b.id,
                business_id=b.business_id,
                business_name=by_id[b.employee_id].business.name if by_id[b.employee_id].business else "",
                employee_id=b.employee_id,
                employee_name=by_id[b.employee_id].name,
                service_name=b.service.name if b.service else "",
                duration_minutes=b.duration_minutes or (b.service.duration_minutes if b.service else None),
                date=b.booking_date,
                time=b.booking_time.strftime("%H:%M"),
                status=b.status,
                client_name=b.client.full_name if b.client else "Клиент",
                client_phone=b.client.phone if b.client else None,
                notes=b.notes,
            )
            for b in bookings
        ],
        days_off=[MasterDayOffOut(employee_id=d.employee_id, date=d.date) for d in days_off],
    )
