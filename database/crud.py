"""
CRUD операции для работы с базой данных
Create, Read, Update, Delete
"""
from datetime import date, time, timedelta
from typing import List, Optional
from sqlalchemy import select, and_, or_, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    User, Business, BusinessOwner, Service, Employee, Booking, EmployeeDayOff, EmployeeService,
    Subscription, SubscriptionService, ClientSubscription, SubscriptionUsage, VenueTimePricing
)


# ===== EXCEPTIONS =====

class OptimisticLockError(Exception):
    """Исключение при конфликте оптимистичной блокировки"""
    pass


ACTIVE_BOOKING_STATUSES = ("pending", "confirmed", "pending_prepayment", "prepayment_sent")
CLIENT_DUPLICATE_STATUSES = ACTIVE_BOOKING_STATUSES


def _booking_lock_dates(booking_date: date) -> list[date]:
    """Dates to lock while checking booking overlap for cross-midnight safety."""
    return sorted({
        booking_date - timedelta(days=1),
        booking_date,
        booking_date + timedelta(days=1),
    })


def _booking_day_lock_params(employee_id: int, lock_date: date) -> dict:
    """PostgreSQL advisory lock params for one employee/day booking window."""
    return {"employee_id": int(employee_id), "day_key": lock_date.toordinal()}


async def _lock_employee_booking_window(
    session: AsyncSession,
    employee_id: Optional[int],
    booking_date: date,
) -> None:
    """Serialize active booking checks for one employee around the target day.

    The application already checks overlapping durations. On PostgreSQL this
    transaction-level advisory lock prevents two concurrent requests from both
    passing that check before either one commits.
    """
    if not employee_id:
        return

    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    for lock_date in _booking_lock_dates(booking_date):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:employee_id, :day_key)"),
            _booking_day_lock_params(employee_id, lock_date),
        )


# ===== USER CRUD =====

async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Получить пользователя по Telegram ID (без создания)"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str],
    full_name: str
) -> User:
    """Получить пользователя или создать нового"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def update_user_phone(session: AsyncSession, user_id: int, phone: str) -> User:
    """Обновить номер телефона пользователя"""
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one()
    user.phone = phone
    await session.commit()
    await session.refresh(user)
    return user


async def can_user_create_business(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """
    Проверить, может ли пользователь создать ещё один бизнес.
    Возвращает (can_create, reason_if_not)

    Проверка идёт через базу MLM бота для актуальных данных о подписке.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        return False, "Пользователь не найден"

    # Если добавлен вручную администратором - без ограничений
    if user.is_manual_owner:
        return True, ""

    # Проверяем подписку через MLM базу данных
    from bot.services.mlm_sync import check_subscription_for_business_creation, get_user_tariff_limits

    can_create, reason = await check_subscription_for_business_creation(user.telegram_id)
    if not can_create:
        return False, reason

    # Получаем лимит бизнесов из MLM базы
    tariff, max_businesses = await get_user_tariff_limits(user.telegram_id)

    # Проверяем лимит бизнесов
    businesses = await get_user_businesses(session, user_id)
    current_count = len(businesses)

    # max_businesses = 0 означает безлимит
    if max_businesses > 0 and current_count >= max_businesses:
        from bot.config import MLM_BOT_USERNAME
        tariff_names = {"standard": "Стандарт", "business": "Бизнес", "network": "Сеть"}
        tariff_name = tariff_names.get(tariff, tariff or "Стандарт")
        return False, f"Достигнут лимит бизнесов для тарифа «{tariff_name}» ({max_businesses}). Перейдите на более высокий тариф через @{MLM_BOT_USERNAME}."

    return True, ""


async def set_user_subscription(
    session: AsyncSession,
    user_id: int,
    tariff: str,
    status: str,
    expires: Optional[date] = None,
    is_manual: bool = False
) -> User:
    """Установить подписку пользователю"""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()

    user.tariff = tariff
    user.subscription_status = status
    user.subscription_expires = expires
    user.is_manual_owner = is_manual

    # Устанавливаем лимит бизнесов по тарифу
    if tariff == "standard":
        user.max_businesses = 1
    elif tariff == "business":
        user.max_businesses = 3
    elif tariff == "network":
        user.max_businesses = 0  # безлимит
    else:
        user.max_businesses = 1

    await session.commit()
    await session.refresh(user)
    return user


async def set_user_as_manual_owner(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Установить пользователя как вручную добавленного владельца (без ограничений)"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user:
        user.is_manual_owner = True
        user.subscription_status = "active"
        user.max_businesses = 0  # безлимит
        await session.commit()
        await session.refresh(user)

    return user


async def get_users_with_subscriptions(session: AsyncSession) -> List[User]:
    """Получить всех пользователей с активными/trial подписками"""
    result = await session.execute(
        select(User).where(
            User.subscription_status.in_(["active", "trial"])
        )
    )
    return list(result.scalars().all())


# ===== BUSINESS CRUD =====

async def create_business(
    session: AsyncSession,
    owner_id: int,
    name: str,
    business_type: str,
    **kwargs
) -> Business:
    """Создать новый бизнес и добавить владельца в business_owners"""
    business = Business(
        owner_id=owner_id,
        name=name,
        business_type=business_type,
        **kwargs
    )
    session.add(business)
    await session.flush()  # Получаем ID бизнеса

    # Автоматически добавляем владельца в business_owners
    business_owner = BusinessOwner(
        business_id=business.id,
        user_id=owner_id,
        role="owner"
    )
    session.add(business_owner)

    await session.commit()
    await session.refresh(business)
    return business


async def get_user_businesses(session: AsyncSession, user_id: int) -> List[Business]:
    """Получить все бизнесы пользователя (через business_owners и legacy owner_id)"""
    # Получаем бизнесы через business_owners
    result1 = await session.execute(
        select(Business)
        .join(BusinessOwner, Business.id == BusinessOwner.business_id)
        .where(BusinessOwner.user_id == user_id)
    )
    businesses_from_owners = set(result1.scalars().all())

    # Fallback: получаем бизнесы через legacy owner_id
    result2 = await session.execute(
        select(Business).where(Business.owner_id == user_id)
    )
    businesses_from_legacy = set(result2.scalars().all())

    # Объединяем результаты (уникальные бизнесы)
    all_businesses = list(businesses_from_owners | businesses_from_legacy)
    return all_businesses


async def get_all_active_businesses(session: AsyncSession) -> List[Business]:
    """Получить все активные бизнесы"""
    result = await session.execute(
        select(Business).where(Business.is_active == True)
    )
    return list(result.scalars().all())


async def get_business_by_id(session: AsyncSession, business_id: int) -> Optional[Business]:
    """Получить бизнес по ID"""
    result = await session.execute(
        select(Business)
        .options(selectinload(Business.owner))
        .where(Business.id == business_id)
    )
    return result.scalar_one_or_none()


async def is_business_owner(session: AsyncSession, business_id: int, user_id: int) -> bool:
    """Проверить, является ли пользователь владельцем бизнеса (через business_owners или legacy owner_id)"""
    # Сначала проверяем в таблице business_owners
    result = await session.execute(
        select(BusinessOwner).where(
            and_(BusinessOwner.business_id == business_id, BusinessOwner.user_id == user_id)
        )
    )
    if result.scalar_one_or_none() is not None:
        return True

    # Fallback на legacy owner_id для обратной совместимости
    result = await session.execute(
        select(Business).where(
            and_(Business.id == business_id, Business.owner_id == user_id)
        )
    )
    return result.scalar_one_or_none() is not None


# ===== SERVICE CRUD =====

async def create_service(
    session: AsyncSession,
    business_id: int,
    name: str,
    duration_minutes: int,
    **kwargs
) -> Service:
    """Создать услугу"""
    service = Service(
        business_id=business_id,
        name=name,
        duration_minutes=duration_minutes,
        **kwargs
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


async def get_business_services(session: AsyncSession, business_id: int) -> List[Service]:
    """Получить все услуги бизнеса"""
    result = await session.execute(
        select(Service).where(
            and_(Service.business_id == business_id, Service.is_active == True)
        ).order_by(Service.sort_order, Service.id)
    )
    return list(result.scalars().all())


async def get_service_by_id(session: AsyncSession, service_id: int) -> Optional[Service]:
    """Получить услугу по ID"""
    result = await session.execute(
        select(Service).where(Service.id == service_id)
    )
    return result.scalar_one_or_none()


async def get_business_main_services(session: AsyncSession, business_id: int) -> List[Service]:
    """Получить основные услуги бизнеса (не дополнительные)"""
    result = await session.execute(
        select(Service).where(
            and_(
                Service.business_id == business_id,
                Service.is_active == True,
                Service.is_additional == False
            )
        ).order_by(Service.sort_order, Service.id)
    )
    return list(result.scalars().all())


async def get_business_additional_services(session: AsyncSession, business_id: int) -> List[Service]:
    """Получить дополнительные услуги бизнеса"""
    result = await session.execute(
        select(Service).where(
            and_(
                Service.business_id == business_id,
                Service.is_active == True,
                Service.is_additional == True
            )
        )
    )
    return list(result.scalars().all())


# ===== EMPLOYEE CRUD =====

async def create_employee(
    session: AsyncSession,
    business_id: int,
    name: str,
    **kwargs
) -> Employee:
    """Создать сотрудника"""
    employee = Employee(
        business_id=business_id,
        name=name,
        **kwargs
    )
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return employee


async def get_business_employees(session: AsyncSession, business_id: int) -> List[Employee]:
    """Получить всех сотрудников бизнеса"""
    result = await session.execute(
        select(Employee).where(
            and_(Employee.business_id == business_id, Employee.is_active == True)
        )
    )
    return list(result.scalars().all())


# ===== BOOKING CRUD =====

async def create_booking(
    session: AsyncSession,
    business_id: int,
    client_id: int,
    service_id: int,
    booking_date: date,
    booking_time: time,
    employee_id: Optional[int] = None,
    status: str = "confirmed",  # По умолчанию записи автоматически подтверждаются
    **kwargs
) -> Booking:
    """Создать запись"""
    from datetime import datetime

    # Получаем длительность текущей услуги
    current_service = await session.execute(
        select(Service).where(Service.id == service_id)
    )
    current_service = current_service.scalar_one_or_none()
    current_duration = current_service.duration_minutes if current_service else 30

    # Проверка на двойное бронирование у мастера (с проверкой пересечения времени)
    if employee_id and current_duration > 0:
        await _lock_employee_booking_window(session, employee_id, booking_date)

        # Cross-midnight: проверяем также предыдущий и следующий день
        prev_day = booking_date - timedelta(days=1)
        next_day = booking_date + timedelta(days=1)
        check_dates = [booking_date, prev_day, next_day]

        conflict_check = await session.execute(
            select(Booking)
            .join(Service, Booking.service_id == Service.id)
            .where(
                and_(
                    Booking.employee_id == employee_id,
                    Booking.booking_date.in_(check_dates),
                    Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                    Service.is_additional == False,
                    Service.duration_minutes > 0
                )
            )
        )
        existing_bookings = conflict_check.scalars().all()

        # Проверяем пересечение времени (абсолютные datetime)
        slot_start = datetime.combine(booking_date, booking_time)
        slot_end = slot_start + timedelta(minutes=current_duration)

        for existing in existing_bookings:
            existing_service = await session.execute(
                select(Service).where(Service.id == existing.service_id)
            )
            existing_service = existing_service.scalar_one_or_none()
            existing_duration = existing_service.duration_minutes if existing_service else 30

            booking_start = datetime.combine(existing.booking_date, existing.booking_time)
            booking_end = booking_start + timedelta(minutes=existing_duration)

            # Проверяем пересечение: НЕ (slot_end <= booking_start ИЛИ slot_start >= booking_end)
            if not (slot_end <= booking_start or slot_start >= booking_end):
                raise ValueError(f"Время {booking_time.strftime('%H:%M')} пересекается с существующей записью")

    # Проверка на дублирование записи одним клиентом (защита от двойного клика)
    client_duplicate_check = await session.execute(
        select(Booking).where(
            and_(
                Booking.client_id == client_id,
                Booking.business_id == business_id,
                Booking.service_id == service_id,
                Booking.booking_date == booking_date,
                Booking.booking_time == booking_time,
                Booking.status.in_(CLIENT_DUPLICATE_STATUSES)
            )
        )
    )
    duplicate_booking = client_duplicate_check.scalar_one_or_none()
    if duplicate_booking:
        # Возвращаем существующую запись вместо создания новой
        return duplicate_booking

    booking = Booking(
        business_id=business_id,
        client_id=client_id,
        service_id=service_id,
        employee_id=employee_id,
        booking_date=booking_date,
        booking_time=booking_time,
        status=status,
        **kwargs
    )
    session.add(booking)

    try:
        await session.commit()
        await session.refresh(booking)
        return booking
    except Exception as e:
        await session.rollback()
        # Если произошла ошибка при commit (например, race condition с дублированием)
        # Проверяем еще раз на конфликт и выдаем понятное сообщение
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise ValueError(f"Время {booking_time.strftime('%H:%M')} уже занято другим клиентом")
        raise


async def get_user_bookings(session: AsyncSession, user_id: int) -> List[Booking]:
    """Получить все записи пользователя"""
    result = await session.execute(
        select(Booking)
        .where(Booking.client_id == user_id)
        .options(
            selectinload(Booking.business).selectinload(Business.owner),
            selectinload(Booking.service),
            selectinload(Booking.employee),
            selectinload(Booking.client)
        )
        .order_by(Booking.booking_date.desc(), Booking.booking_time.desc())
    )
    return list(result.scalars().all())


async def get_business_bookings(
    session: AsyncSession,
    business_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[Booking]:
    """Получить записи бизнеса за период или все"""
    query = select(Booking).where(Booking.business_id == business_id)

    if start_date:
        query = query.where(Booking.booking_date >= start_date)
    if end_date:
        query = query.where(Booking.booking_date <= end_date)

    query = query.options(
        selectinload(Booking.client),
        selectinload(Booking.service),
        selectinload(Booking.employee)
    ).order_by(Booking.booking_date, Booking.booking_time)

    result = await session.execute(query)
    return list(result.scalars().all())


async def update_booking_status(
    session: AsyncSession,
    booking_id: int,
    status: str
) -> Booking:
    """Обновить статус записи"""
    result = await session.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one()
    booking.status = status
    await session.commit()
    await session.refresh(booking)
    return booking


async def get_booking_by_id(session: AsyncSession, booking_id: int) -> Optional[Booking]:
    """Получить запись по ID"""
    result = await session.execute(
        select(Booking)
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.employee),
            selectinload(Booking.business).selectinload(Business.owner)
        )
        .where(Booking.id == booking_id)
    )
    return result.scalar_one_or_none()


async def get_pending_reminders(session: AsyncSession) -> List[Booking]:
    """Получить записи, для которых нужно отправить напоминание"""
    # Записи на завтра, для которых еще не отправлялось напоминание
    result = await session.execute(
        select(Booking)
        .where(
            and_(
                Booking.status == "pending",
                Booking.reminder_sent == False
            )
        )
        .options(
            selectinload(Booking.client),
            selectinload(Booking.business),
            selectinload(Booking.service)
        )
    )
    return list(result.scalars().all())


async def mark_reminder_sent(session: AsyncSession, booking_id: int):
    """Отметить, что напоминание отправлено"""
    result = await session.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one()
    booking.reminder_sent = True
    await session.commit()


async def get_employee_by_id(session: AsyncSession, employee_id: int) -> Optional[Employee]:
    """Получить сотрудника по ID"""
    result = await session.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    return result.scalar_one_or_none()


async def delete_service(session: AsyncSession, service_id: int):
    """Удалить услугу"""
    # Сначала удаляем связанные бронирования
    await session.execute(
        delete(Booking).where(Booking.service_id == service_id)
    )
    # Удаляем связи с сотрудниками (employee_services)
    await session.execute(
        delete(EmployeeService).where(EmployeeService.service_id == service_id)
    )
    # Затем удаляем саму услугу
    result = await session.execute(
        select(Service).where(Service.id == service_id)
    )
    service = result.scalar_one()
    await session.delete(service)
    await session.commit()


async def delete_employee(session: AsyncSession, employee_id: int):
    """Удалить сотрудника"""
    # Сначала удаляем связанные записи (bookings), где employee_id указывает на этого сотрудника
    await session.execute(
        delete(Booking).where(Booking.employee_id == employee_id)
    )
    # Затем удаляем самого сотрудника
    await session.execute(
        delete(Employee).where(Employee.id == employee_id)
    )
    await session.commit()


# ===== MASTER FUNCTIONS =====

async def get_employee_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[Employee]:
    """Получить первого сотрудника по Telegram ID (для обратной совместимости)"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(Employee.telegram_id == telegram_id)
    )
    return result.scalars().first()


async def get_employees_by_telegram_id(session: AsyncSession, telegram_id: int) -> List[Employee]:
    """Получить ВСЕХ сотрудников по Telegram ID (один человек может работать в нескольких бизнесах)"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(Employee.telegram_id == telegram_id, Employee.is_active == True)
    )
    return list(result.scalars().all())


async def get_administrator_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[Employee]:
    """Получить первого администратора по Telegram ID (для обратной совместимости)"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(
            Employee.telegram_id == telegram_id,
            Employee.role.in_(["administrator", "master_and_admin"]),
            Employee.is_active == True
        )
    )
    return result.scalars().first()


async def get_administrators_by_telegram_id(session: AsyncSession, telegram_id: int) -> List[Employee]:
    """Получить ВСЕХ администраторов по Telegram ID (один человек может быть админом в нескольких бизнесах)"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(
            Employee.telegram_id == telegram_id,
            Employee.role.in_(["administrator", "master_and_admin"]),
            Employee.is_active == True
        )
    )
    return list(result.scalars().all())


async def get_master_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[Employee]:
    """Получить первого мастера по Telegram ID (для обратной совместимости)"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(
            Employee.telegram_id == telegram_id,
            Employee.role.in_(["master", "master_and_admin"]),
            Employee.is_active == True
        )
    )
    return result.scalars().first()


async def get_masters_by_telegram_id(session: AsyncSession, telegram_id: int) -> List[Employee]:
    """Получить ВСЕХ мастеров по Telegram ID"""
    result = await session.execute(
        select(Employee)
        .options(selectinload(Employee.business))
        .where(
            Employee.telegram_id == telegram_id,
            Employee.role.in_(["master", "master_and_admin"]),
            Employee.is_active == True
        )
    )
    return list(result.scalars().all())


async def get_master_bookings(
    session: AsyncSession,
    employee_id: int,
    start_date: date,
    end_date: date
) -> List[Booking]:
    """Получить записи мастера за период"""
    result = await session.execute(
        select(Booking)
        .options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.business)
        )
        .where(Booking.employee_id == employee_id)
        .where(Booking.booking_date >= start_date)
        .where(Booking.booking_date <= end_date)
        .where(Booking.status.in_(["pending", "confirmed", "completed"]))
        .order_by(Booking.booking_date, Booking.booking_time)
    )
    return list(result.scalars().all())


# ===== EMPLOYEE DAYS OFF CRUD =====

async def add_employee_day_off(
    session: AsyncSession,
    employee_id: int,
    day_off_date: date,
    reason: Optional[str] = None
) -> EmployeeDayOff:
    """Добавить выходной день сотруднику"""
    # Проверяем, не добавлен ли уже этот день
    existing = await session.execute(
        select(EmployeeDayOff).where(
            EmployeeDayOff.employee_id == employee_id,
            EmployeeDayOff.date == day_off_date
        )
    )
    if existing.scalar_one_or_none():
        return None  # День уже добавлен

    day_off = EmployeeDayOff(
        employee_id=employee_id,
        date=day_off_date,
        reason=reason
    )
    session.add(day_off)
    await session.commit()
    await session.refresh(day_off)
    return day_off


async def remove_employee_day_off(
    session: AsyncSession,
    employee_id: int,
    day_off_date: date
) -> bool:
    """Удалить выходной день сотрудника"""
    result = await session.execute(
        delete(EmployeeDayOff).where(
            EmployeeDayOff.employee_id == employee_id,
            EmployeeDayOff.date == day_off_date
        )
    )
    await session.commit()
    return result.rowcount > 0


async def get_employee_days_off(
    session: AsyncSession,
    employee_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[EmployeeDayOff]:
    """Получить выходные дни сотрудника"""
    query = select(EmployeeDayOff).where(EmployeeDayOff.employee_id == employee_id)

    if start_date:
        query = query.where(EmployeeDayOff.date >= start_date)
    if end_date:
        query = query.where(EmployeeDayOff.date <= end_date)

    query = query.order_by(EmployeeDayOff.date)
    result = await session.execute(query)
    return list(result.scalars().all())


async def is_employee_day_off(
    session: AsyncSession,
    employee_id: int,
    check_date: date
) -> bool:
    """Проверить, является ли дата выходным днем сотрудника"""
    result = await session.execute(
        select(EmployeeDayOff).where(
            EmployeeDayOff.employee_id == employee_id,
            EmployeeDayOff.date == check_date
        )
    )
    return result.scalar_one_or_none() is not None


async def get_business_employees_days_off(
    session: AsyncSession,
    business_id: int,
    check_date: date
) -> List[int]:
    """Получить список ID сотрудников бизнеса, у которых выходной в указанную дату"""
    result = await session.execute(
        select(EmployeeDayOff.employee_id)
        .join(Employee)
        .where(
            Employee.business_id == business_id,
            EmployeeDayOff.date == check_date
        )
    )
    return list(result.scalars().all())


# ===== EMPLOYEE SERVICES CRUD =====

async def add_employee_service(
    session: AsyncSession,
    employee_id: int,
    service_id: int
) -> Optional[EmployeeService]:
    """Добавить связь между сотрудником и услугой (мастер может делать эту услугу)"""
    # Проверяем, не добавлена ли уже эта связь
    existing = await session.execute(
        select(EmployeeService).where(
            EmployeeService.employee_id == employee_id,
            EmployeeService.service_id == service_id
        )
    )
    if existing.scalar_one_or_none():
        return None  # Связь уже существует

    employee_service = EmployeeService(
        employee_id=employee_id,
        service_id=service_id
    )
    session.add(employee_service)
    await session.commit()
    await session.refresh(employee_service)
    return employee_service


async def remove_employee_service(
    session: AsyncSession,
    employee_id: int,
    service_id: int
) -> bool:
    """Удалить связь между сотрудником и услугой"""
    result = await session.execute(
        delete(EmployeeService).where(
            EmployeeService.employee_id == employee_id,
            EmployeeService.service_id == service_id
        )
    )
    await session.commit()
    return result.rowcount > 0


async def get_employee_services(
    session: AsyncSession,
    employee_id: int
) -> List[Service]:
    """Получить список услуг, которые может делать сотрудник"""
    result = await session.execute(
        select(Service)
        .join(EmployeeService)
        .where(
            EmployeeService.employee_id == employee_id,
            Service.is_active == True
        )
    )
    return list(result.scalars().all())


async def get_employee_service_ids(
    session: AsyncSession,
    employee_id: int
) -> List[int]:
    """Получить список ID услуг, которые может делать сотрудник"""
    result = await session.execute(
        select(EmployeeService.service_id)
        .where(EmployeeService.employee_id == employee_id)
    )
    return list(result.scalars().all())


async def get_employees_for_service(
    session: AsyncSession,
    service_id: int,
    business_id: int
) -> List[Employee]:
    """Получить список активных мастеров, которые могут делать указанную услугу"""
    result = await session.execute(
        select(Employee)
        .join(EmployeeService)
        .where(
            EmployeeService.service_id == service_id,
            Employee.business_id == business_id,
            Employee.is_active == True,
            Employee.role.in_(["master", "master_and_admin"])
        )
    )
    return list(result.scalars().all())


async def get_employees_for_services(
    session: AsyncSession,
    service_ids: List[int],
    business_id: int
) -> List[Employee]:
    """Получить список мастеров, которые могут делать ВСЕ указанные услуги"""
    if not service_ids:
        return []

    # Для каждой услуги получаем список мастеров
    # Ищем пересечение - мастеров, которые могут делать все услуги
    first_service_id = service_ids[0]
    result = await session.execute(
        select(Employee)
        .join(EmployeeService)
        .where(
            EmployeeService.service_id == first_service_id,
            Employee.business_id == business_id,
            Employee.is_active == True,
            Employee.role.in_(["master", "master_and_admin"])
        )
    )
    candidates = list(result.scalars().all())

    # Фильтруем кандидатов - оставляем только тех, кто может делать ВСЕ услуги
    final_employees = []
    for emp in candidates:
        emp_service_ids = await get_employee_service_ids(session, emp.id)
        if all(sid in emp_service_ids for sid in service_ids):
            final_employees.append(emp)

    return final_employees


async def set_employee_services(
    session: AsyncSession,
    employee_id: int,
    service_ids: List[int]
) -> None:
    """Установить список услуг для сотрудника (заменяет существующие)"""
    # Удаляем все текущие связи
    await session.execute(
        delete(EmployeeService).where(EmployeeService.employee_id == employee_id)
    )
    # Важно: flush чтобы delete выполнился до insert
    await session.flush()

    # Убираем дубликаты из списка
    unique_service_ids = list(set(service_ids))

    # Добавляем новые связи
    for service_id in unique_service_ids:
        employee_service = EmployeeService(
            employee_id=employee_id,
            service_id=service_id
        )
        session.add(employee_service)

    await session.commit()


async def can_employee_do_service(
    session: AsyncSession,
    employee_id: int,
    service_id: int
) -> bool:
    """Проверить, может ли сотрудник делать указанную услугу"""
    result = await session.execute(
        select(EmployeeService).where(
            EmployeeService.employee_id == employee_id,
            EmployeeService.service_id == service_id
        )
    )
    return result.scalar_one_or_none() is not None


# ===== SUBSCRIPTION CRUD (Владелец) =====

async def create_subscription(
    session: AsyncSession,
    business_id: int,
    name: str,
    price: int,
    validity_days: int,
    services_with_quantities: List[tuple],  # [(service_id, quantity), ...]
    description: Optional[str] = None,
    rules: Optional[str] = None
) -> Subscription:
    """Создать абонемент с услугами"""
    subscription = Subscription(
        business_id=business_id,
        name=name,
        price=price,
        validity_days=validity_days,
        description=description,
        rules=rules
    )
    session.add(subscription)
    await session.flush()  # Получаем ID абонемента

    # Добавляем услуги
    for service_id, quantity in services_with_quantities:
        sub_service = SubscriptionService(
            subscription_id=subscription.id,
            service_id=service_id,
            quantity=quantity
        )
        session.add(sub_service)

    await session.commit()
    await session.refresh(subscription)
    return subscription


async def get_business_subscriptions(
    session: AsyncSession,
    business_id: int,
    active_only: bool = True
) -> List[Subscription]:
    """Получить все абонементы бизнеса"""
    query = select(Subscription).where(Subscription.business_id == business_id)
    if active_only:
        query = query.where(Subscription.is_active == True)
    query = query.options(
        selectinload(Subscription.services).selectinload(SubscriptionService.service)
    ).order_by(Subscription.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_subscription_by_id(
    session: AsyncSession,
    subscription_id: int
) -> Optional[Subscription]:
    """Получить абонемент по ID"""
    result = await session.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.services).selectinload(SubscriptionService.service),
            selectinload(Subscription.business)
        )
        .where(Subscription.id == subscription_id)
    )
    return result.scalar_one_or_none()


async def update_subscription(
    session: AsyncSession,
    subscription_id: int,
    **kwargs
) -> Optional[Subscription]:
    """Обновить абонемент"""
    result = await session.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return None

    for key, value in kwargs.items():
        if hasattr(subscription, key):
            setattr(subscription, key, value)

    await session.commit()
    await session.refresh(subscription)
    return subscription


async def update_subscription_services(
    session: AsyncSession,
    subscription_id: int,
    services_with_quantities: List[tuple]  # [(service_id, quantity), ...]
) -> None:
    """Обновить услуги в абонементе"""
    # Удаляем старые связи
    await session.execute(
        delete(SubscriptionService).where(SubscriptionService.subscription_id == subscription_id)
    )
    await session.flush()

    # Добавляем новые
    for service_id, quantity in services_with_quantities:
        sub_service = SubscriptionService(
            subscription_id=subscription_id,
            service_id=service_id,
            quantity=quantity
        )
        session.add(sub_service)

    await session.commit()


async def delete_subscription(
    session: AsyncSession,
    subscription_id: int
) -> bool:
    """Удалить абонемент (помечаем как неактивный)"""
    result = await session.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return False

    subscription.is_active = False
    await session.commit()
    return True


# ===== SUBSCRIPTION CRUD (Клиент) =====

async def purchase_subscription(
    session: AsyncSession,
    subscription_id: int,
    client_id: int,
    business_id: int
) -> ClientSubscription:
    """Купить абонемент (создать запись о покупке, статус pending_payment)"""
    from datetime import timedelta

    # Получаем информацию об абонементе для расчета срока
    subscription = await get_subscription_by_id(session, subscription_id)
    if not subscription:
        raise ValueError("Абонемент не найден")

    from datetime import datetime
    expires_at = datetime.utcnow() + timedelta(days=subscription.validity_days)

    client_sub = ClientSubscription(
        subscription_id=subscription_id,
        client_id=client_id,
        business_id=business_id,
        expires_at=expires_at,
        status="pending_payment"
    )
    session.add(client_sub)
    await session.commit()
    await session.refresh(client_sub)
    return client_sub


async def get_client_subscriptions(
    session: AsyncSession,
    client_id: int,
    business_id: Optional[int] = None,
    active_only: bool = False
) -> List[ClientSubscription]:
    """Получить абонементы клиента"""
    query = select(ClientSubscription).where(ClientSubscription.client_id == client_id)

    if business_id:
        query = query.where(ClientSubscription.business_id == business_id)

    if active_only:
        from datetime import datetime
        query = query.where(
            ClientSubscription.status == "active",
            ClientSubscription.expires_at > datetime.utcnow()
        )

    query = query.options(
        selectinload(ClientSubscription.subscription).selectinload(Subscription.services).selectinload(SubscriptionService.service),
        selectinload(ClientSubscription.usages),
        selectinload(ClientSubscription.business)
    ).order_by(ClientSubscription.purchased_at.desc())

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_client_subscription_by_id(
    session: AsyncSession,
    client_subscription_id: int
) -> Optional[ClientSubscription]:
    """Получить купленный абонемент по ID"""
    result = await session.execute(
        select(ClientSubscription)
        .options(
            selectinload(ClientSubscription.subscription).selectinload(Subscription.services).selectinload(SubscriptionService.service),
            selectinload(ClientSubscription.usages).selectinload(SubscriptionUsage.service),
            selectinload(ClientSubscription.business).selectinload(Business.owner),
            selectinload(ClientSubscription.client)
        )
        .where(ClientSubscription.id == client_subscription_id)
    )
    return result.scalar_one_or_none()


async def update_client_subscription_status(
    session: AsyncSession,
    client_subscription_id: int,
    status: str,
    **kwargs
) -> Optional[ClientSubscription]:
    """Обновить статус купленного абонемента"""
    result = await session.execute(
        select(ClientSubscription).where(ClientSubscription.id == client_subscription_id)
    )
    client_sub = result.scalar_one_or_none()
    if not client_sub:
        return None

    client_sub.status = status
    for key, value in kwargs.items():
        if hasattr(client_sub, key):
            setattr(client_sub, key, value)

    await session.commit()
    await session.refresh(client_sub)
    return client_sub


async def set_payment_receipt(
    session: AsyncSession,
    client_subscription_id: int,
    receipt_file_id: str
) -> Optional[ClientSubscription]:
    """Прикрепить чек к абонементу"""
    result = await session.execute(
        select(ClientSubscription)
        .options(
            selectinload(ClientSubscription.subscription),
            selectinload(ClientSubscription.business).selectinload(Business.owner),
            selectinload(ClientSubscription.client)
        )
        .where(ClientSubscription.id == client_subscription_id)
    )
    client_sub = result.scalar_one_or_none()
    if not client_sub:
        return None

    client_sub.payment_receipt = receipt_file_id
    client_sub.status = "payment_sent"
    await session.commit()
    return client_sub


async def confirm_subscription_payment(
    session: AsyncSession,
    client_subscription_id: int
) -> Optional[ClientSubscription]:
    """Подтвердить оплату абонемента (владелец)"""
    from datetime import datetime, timedelta

    result = await session.execute(
        select(ClientSubscription)
        .options(selectinload(ClientSubscription.subscription))
        .where(ClientSubscription.id == client_subscription_id)
    )
    client_sub = result.scalar_one_or_none()
    if not client_sub:
        return None

    # Срок действия начинается с момента подтверждения
    client_sub.status = "active"
    client_sub.payment_confirmed_at = datetime.utcnow()
    client_sub.expires_at = datetime.utcnow() + timedelta(days=client_sub.subscription.validity_days)

    await session.commit()
    await session.refresh(client_sub)
    return client_sub


async def get_subscription_remaining(
    session: AsyncSession,
    client_subscription_id: int
) -> dict:
    """Получить остаток услуг в абонементе"""
    client_sub = await get_client_subscription_by_id(session, client_subscription_id)
    if not client_sub:
        return {}

    remaining = {}
    for sub_service in client_sub.subscription.services:
        service_id = sub_service.service_id
        total = sub_service.quantity
        used = sum(1 for u in client_sub.usages if u.service_id == service_id)
        remaining[service_id] = {
            "service_name": sub_service.service.name,
            "total": total,
            "used": used,
            "remaining": total - used
        }

    return remaining


async def check_subscription_service_available(
    session: AsyncSession,
    client_subscription_id: int,
    service_id: int
) -> bool:
    """Проверить, доступна ли услуга в абонементе (есть остаток)"""
    remaining = await get_subscription_remaining(session, client_subscription_id)
    if service_id not in remaining:
        return False
    return remaining[service_id]["remaining"] > 0


async def use_subscription_service(
    session: AsyncSession,
    client_subscription_id: int,
    service_id: int,
    booking_id: Optional[int] = None
) -> Optional[SubscriptionUsage]:
    """Использовать услугу из абонемента"""
    # Проверяем доступность
    if not await check_subscription_service_available(session, client_subscription_id, service_id):
        return None

    usage = SubscriptionUsage(
        client_subscription_id=client_subscription_id,
        service_id=service_id,
        booking_id=booking_id
    )
    session.add(usage)
    await session.commit()
    await session.refresh(usage)

    # Проверяем, не закончился ли абонемент (все услуги использованы)
    remaining = await get_subscription_remaining(session, client_subscription_id)
    all_depleted = all(r["remaining"] <= 0 for r in remaining.values())
    if all_depleted:
        await update_client_subscription_status(session, client_subscription_id, "depleted")

    return usage


async def get_client_available_services(
    session: AsyncSession,
    client_id: int,
    business_id: int
) -> List[dict]:
    """Получить все доступные услуги из активных абонементов клиента"""
    client_subs = await get_client_subscriptions(
        session, client_id, business_id=business_id, active_only=True
    )

    available_services = []
    for client_sub in client_subs:
        remaining = await get_subscription_remaining(session, client_sub.id)
        for service_id, info in remaining.items():
            if info["remaining"] > 0:
                available_services.append({
                    "client_subscription_id": client_sub.id,
                    "subscription_name": client_sub.subscription.name,
                    "service_id": service_id,
                    "service_name": info["service_name"],
                    "remaining": info["remaining"],
                    "expires_at": client_sub.expires_at
                })

    return available_services


# ===== SUBSCRIPTION ANALYTICS =====

async def get_sold_subscriptions(
    session: AsyncSession,
    business_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[ClientSubscription]:
    """Получить проданные абонементы бизнеса за период"""
    from datetime import datetime, time as dt_time

    query = select(ClientSubscription).where(ClientSubscription.business_id == business_id)

    if start_date:
        start_datetime = datetime.combine(start_date, dt_time.min)
        query = query.where(ClientSubscription.purchased_at >= start_datetime)
    if end_date:
        end_datetime = datetime.combine(end_date, dt_time.max)
        query = query.where(ClientSubscription.purchased_at <= end_datetime)

    query = query.options(
        selectinload(ClientSubscription.subscription),
        selectinload(ClientSubscription.client),
        selectinload(ClientSubscription.usages)
    ).order_by(ClientSubscription.purchased_at.desc())

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_expiring_subscriptions(
    session: AsyncSession,
    days_until_expiry: int = 7
) -> List[ClientSubscription]:
    """Получить абонементы, истекающие в ближайшие N дней"""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    expiry_threshold = now + timedelta(days=days_until_expiry)

    result = await session.execute(
        select(ClientSubscription)
        .options(
            selectinload(ClientSubscription.subscription),
            selectinload(ClientSubscription.client),
            selectinload(ClientSubscription.business)
        )
        .where(
            ClientSubscription.status == "active",
            ClientSubscription.expires_at > now,
            ClientSubscription.expires_at <= expiry_threshold,
            ClientSubscription.expiry_reminder_sent == False
        )
    )
    return list(result.scalars().all())


async def mark_expiry_reminder_sent(
    session: AsyncSession,
    client_subscription_id: int
) -> None:
    """Отметить, что напоминание об истечении отправлено"""
    result = await session.execute(
        select(ClientSubscription).where(ClientSubscription.id == client_subscription_id)
    )
    client_sub = result.scalar_one_or_none()
    if client_sub:
        client_sub.expiry_reminder_sent = True
        await session.commit()


async def get_pending_payment_subscriptions(
    session: AsyncSession,
    business_id: int
) -> List[ClientSubscription]:
    """Получить абонементы, ожидающие подтверждения оплаты"""
    result = await session.execute(
        select(ClientSubscription)
        .options(
            selectinload(ClientSubscription.subscription),
            selectinload(ClientSubscription.client)
        )
        .where(
            ClientSubscription.business_id == business_id,
            ClientSubscription.status == "payment_sent"
        )
        .order_by(ClientSubscription.purchased_at.desc())
    )
    return list(result.scalars().all())


async def get_business_clients(
    session: AsyncSession,
    business_id: int,
    limit: int = 100
) -> List[User]:
    """Получить клиентов бизнеса (по записям)"""
    result = await session.execute(
        select(User)
        .join(Booking, Booking.client_id == User.id)
        .where(Booking.business_id == business_id)
        .distinct()
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_business_subscriptions_stats(
    session: AsyncSession,
    business_id: int,
    start_date,
    end_date
) -> dict:
    """Получить статистику абонементов бизнеса"""
    from datetime import datetime

    # Активные абонементы
    active_result = await session.execute(
        select(func.count())
        .select_from(ClientSubscription)
        .where(
            ClientSubscription.business_id == business_id,
            ClientSubscription.status == "active"
        )
    )
    active_count = active_result.scalar() or 0

    # Проданные за период
    sold_result = await session.execute(
        select(ClientSubscription)
        .options(selectinload(ClientSubscription.subscription))
        .where(
            ClientSubscription.business_id == business_id,
            ClientSubscription.status.in_(["active", "payment_sent", "expired", "depleted"]),
            ClientSubscription.purchased_at >= datetime.combine(start_date, datetime.min.time()),
            ClientSubscription.purchased_at <= datetime.combine(end_date, datetime.max.time())
        )
    )
    sold_subs = list(sold_result.scalars().all())
    sold_count = len(sold_subs)

    # Выручка с абонементов
    revenue = sum(cs.subscription.price for cs in sold_subs if cs.subscription and cs.status == "active")

    return {
        'active_count': active_count,
        'sold_count': sold_count,
        'revenue': revenue
    }


# ===== BUSINESS OWNERS CRUD =====

async def get_business_owners(session: AsyncSession, business_id: int) -> List[User]:
    """Получить всех владельцев бизнеса"""
    result = await session.execute(
        select(User)
        .join(BusinessOwner, User.id == BusinessOwner.user_id)
        .where(BusinessOwner.business_id == business_id)
    )
    owners = list(result.scalars().all())

    # Fallback: если в business_owners никого нет, получаем legacy owner
    if not owners:
        result = await session.execute(
            select(User)
            .join(Business, User.id == Business.owner_id)
            .where(Business.id == business_id)
        )
        legacy_owner = result.scalar_one_or_none()
        if legacy_owner:
            owners = [legacy_owner]

    return owners


async def get_business_owners_with_roles(session: AsyncSession, business_id: int) -> List[dict]:
    """Получить владельцев бизнеса с их ролями"""
    result = await session.execute(
        select(BusinessOwner, User)
        .join(User, BusinessOwner.user_id == User.id)
        .where(BusinessOwner.business_id == business_id)
    )
    owners_data = []
    for bo, user in result.all():
        owners_data.append({
            'user': user,
            'role': bo.role,
            'added_at': bo.added_at,
            'added_by_id': bo.added_by_id
        })

    # Fallback: если в business_owners никого нет
    if not owners_data:
        result = await session.execute(
            select(Business).options(selectinload(Business.owner)).where(Business.id == business_id)
        )
        business = result.scalar_one_or_none()
        if business and business.owner:
            owners_data.append({
                'user': business.owner,
                'role': 'owner',
                'added_at': business.created_at,
                'added_by_id': None
            })

    return owners_data


async def add_business_owner(
    session: AsyncSession,
    business_id: int,
    user_id: int,
    role: str = "co_owner",
    added_by_id: Optional[int] = None
) -> Optional[BusinessOwner]:
    """Добавить владельца к бизнесу"""
    # Проверяем, не добавлен ли уже этот пользователь
    existing = await session.execute(
        select(BusinessOwner).where(
            and_(BusinessOwner.business_id == business_id, BusinessOwner.user_id == user_id)
        )
    )
    if existing.scalar_one_or_none():
        return None  # Уже является владельцем

    business_owner = BusinessOwner(
        business_id=business_id,
        user_id=user_id,
        role=role,
        added_by_id=added_by_id
    )
    session.add(business_owner)
    await session.commit()
    await session.refresh(business_owner)
    return business_owner


async def remove_business_owner(
    session: AsyncSession,
    business_id: int,
    user_id: int
) -> tuple[bool, str]:
    """
    Удалить владельца из бизнеса.
    Возвращает (success, message).
    Защита: нельзя удалить последнего владельца.
    """
    # Получаем количество владельцев
    count_result = await session.execute(
        select(func.count()).select_from(BusinessOwner).where(BusinessOwner.business_id == business_id)
    )
    owners_count = count_result.scalar() or 0

    # Проверяем legacy owner_id
    business_result = await session.execute(
        select(Business).where(Business.id == business_id)
    )
    business = business_result.scalar_one_or_none()
    if not business:
        return False, "Бизнес не найден"

    # Если это единственный владелец в business_owners и совпадает с legacy owner_id
    if owners_count <= 1 and business.owner_id == user_id:
        return False, "Нельзя удалить последнего владельца бизнеса"

    # Если пытаемся удалить legacy owner и он единственный
    if owners_count == 0 and business.owner_id == user_id:
        return False, "Нельзя удалить последнего владельца бизнеса"

    # Удаляем из business_owners
    result = await session.execute(
        delete(BusinessOwner).where(
            and_(BusinessOwner.business_id == business_id, BusinessOwner.user_id == user_id)
        )
    )
    await session.commit()

    if result.rowcount > 0:
        return True, "Владелец удалён"
    return False, "Владелец не найден"


async def get_owners_count(session: AsyncSession, business_id: int) -> int:
    """Получить количество владельцев бизнеса"""
    result = await session.execute(
        select(func.count()).select_from(BusinessOwner).where(BusinessOwner.business_id == business_id)
    )
    count = result.scalar() or 0

    # Fallback: если в business_owners никого нет, проверяем legacy
    if count == 0:
        result = await session.execute(
            select(Business).where(Business.id == business_id)
        )
        business = result.scalar_one_or_none()
        if business and business.owner_id:
            count = 1

    return count


# ===== OPTIMISTIC LOCKING =====

async def update_booking_with_lock(
    session: AsyncSession,
    booking_id: int,
    updates: dict,
    expected_version: int
) -> Booking:
    """
    Обновить бронирование с проверкой версии (оптимистичная блокировка).
    Raises OptimisticLockError при конфликте версий.
    """
    result = await session.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()

    if not booking:
        raise ValueError("Бронирование не найдено")

    if booking.version != expected_version:
        raise OptimisticLockError(
            f"Данные были изменены другим пользователем. "
            f"Ожидаемая версия: {expected_version}, текущая: {booking.version}"
        )

    # Применяем обновления
    for key, value in updates.items():
        if hasattr(booking, key) and key != 'version':
            setattr(booking, key, value)

    # Инкрементируем версию
    booking.version += 1

    await session.commit()
    await session.refresh(booking)
    return booking


async def update_business_with_lock(
    session: AsyncSession,
    business_id: int,
    updates: dict,
    expected_version: int
) -> Business:
    """
    Обновить бизнес с проверкой версии (оптимистичная блокировка).
    Raises OptimisticLockError при конфликте версий.
    """
    result = await session.execute(
        select(Business).where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()

    if not business:
        raise ValueError("Бизнес не найден")

    if business.version != expected_version:
        raise OptimisticLockError(
            f"Данные были изменены другим пользователем. "
            f"Ожидаемая версия: {expected_version}, текущая: {business.version}"
        )

    # Применяем обновления
    for key, value in updates.items():
        if hasattr(business, key) and key != 'version':
            setattr(business, key, value)

    # Инкрементируем версию
    business.version += 1

    await session.commit()
    await session.refresh(business)
    return business


async def update_service_with_lock(
    session: AsyncSession,
    service_id: int,
    updates: dict,
    expected_version: int
) -> Service:
    """
    Обновить услугу с проверкой версии (оптимистичная блокировка).
    Raises OptimisticLockError при конфликте версий.
    """
    result = await session.execute(
        select(Service).where(Service.id == service_id)
    )
    service = result.scalar_one_or_none()

    if not service:
        raise ValueError("Услуга не найдена")

    if service.version != expected_version:
        raise OptimisticLockError(
            f"Данные были изменены другим пользователем. "
            f"Ожидаемая версия: {expected_version}, текущая: {service.version}"
        )

    # Применяем обновления
    for key, value in updates.items():
        if hasattr(service, key) and key != 'version':
            setattr(service, key, value)

    # Инкрементируем версию
    service.version += 1

    await session.commit()
    await session.refresh(service)
    return service


async def ensure_owner_in_business_owners(session: AsyncSession, business_id: int, user_id: int) -> None:
    """Убедиться, что владелец добавлен в business_owners (для обратной совместимости)"""
    existing = await session.execute(
        select(BusinessOwner).where(
            and_(BusinessOwner.business_id == business_id, BusinessOwner.user_id == user_id)
        )
    )
    if existing.scalar_one_or_none() is None:
        business_owner = BusinessOwner(
            business_id=business_id,
            user_id=user_id,
            role="owner"
        )
        session.add(business_owner)
        await session.commit()


# ===== VENUE TIME PRICING =====

async def create_venue_time_pricing(
    session: AsyncSession,
    employee_id: int,
    time_from: time,
    time_to: time,
    price_per_hour: int,
    day_type: str = "all"
) -> VenueTimePricing:
    """Создать тариф аренды помещения по времени суток"""
    pricing = VenueTimePricing(
        employee_id=employee_id,
        time_from=time_from,
        time_to=time_to,
        price_per_hour=price_per_hour,
        day_type=day_type
    )
    session.add(pricing)
    await session.commit()
    await session.refresh(pricing)
    return pricing


async def get_employee_time_pricing(
    session: AsyncSession,
    employee_id: int,
    booking_date: date = None
) -> List[VenueTimePricing]:
    """Получить тарифы аренды помещения, отсортированные по time_from.

    Если booking_date указан, фильтрует по day_type (будни/выходные).
    """
    result = await session.execute(
        select(VenueTimePricing)
        .where(VenueTimePricing.employee_id == employee_id)
        .order_by(VenueTimePricing.time_from)
    )
    rules = list(result.scalars().all())

    if booking_date is not None:
        # 0=Monday...6=Sunday; выходные = 5,6
        is_weekend = booking_date.weekday() >= 5
        filtered = []
        for rule in rules:
            day_type = getattr(rule, 'day_type', 'all') or 'all'
            if day_type == 'all':
                filtered.append(rule)
            elif day_type == 'weekday' and not is_weekend:
                filtered.append(rule)
            elif day_type == 'weekend' and is_weekend:
                filtered.append(rule)
        return filtered

    return rules


async def delete_venue_time_pricing(
    session: AsyncSession,
    pricing_id: int
) -> bool:
    """Удалить тариф аренды помещения"""
    result = await session.execute(
        select(VenueTimePricing).where(VenueTimePricing.id == pricing_id)
    )
    pricing = result.scalar_one_or_none()
    if pricing:
        await session.delete(pricing)
        await session.commit()
        return True
    return False


async def calculate_time_based_price(
    session: AsyncSession,
    employee_id: int,
    start_time: time,
    duration_minutes: int,
    booking_date: date = None
) -> Optional[int]:
    """Рассчитать стоимость бронирования на основе тарифов по времени суток.

    Возвращает None если тарифов нет (используется фиксированная цена услуги).
    Разбивает бронирование на отрезки по тарифным зонам и суммирует стоимость.
    """
    rules = await get_employee_time_pricing(session, employee_id, booking_date=booking_date)
    if not rules:
        return None

    from datetime import datetime as dt, timedelta

    # Конвертируем start_time в минуты от начала суток для удобства расчётов
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = start_minutes + duration_minutes
    total_price = 0

    current = start_minutes
    while current < end_minutes:
        # Ищем подходящий тариф для текущей минуты
        current_time = time(hour=(current % 1440) // 60, minute=(current % 1440) % 60)
        matched_rule = None

        for rule in rules:
            rule_from_min = rule.time_from.hour * 60 + rule.time_from.minute
            rule_to_min = rule.time_to.hour * 60 + rule.time_to.minute

            if rule_to_min > rule_from_min:
                # Обычный интервал (например 09:00-18:00)
                if rule_from_min <= (current % 1440) < rule_to_min:
                    matched_rule = rule
                    break
            else:
                # Интервал через полночь (например 22:00-06:00)
                if (current % 1440) >= rule_from_min or (current % 1440) < rule_to_min:
                    matched_rule = rule
                    break

        if not matched_rule:
            # Нет тарифа для этого времени — пропускаем минуту
            current += 1
            continue

        # Определяем сколько минут попадает в этот тариф
        rule_from_min = matched_rule.time_from.hour * 60 + matched_rule.time_from.minute
        rule_to_min = matched_rule.time_to.hour * 60 + matched_rule.time_to.minute

        if rule_to_min > rule_from_min:
            # Обычный интервал
            range_end = rule_to_min
        else:
            # Через полночь
            if (current % 1440) >= rule_from_min:
                range_end = 1440 + rule_to_min  # до конца суток + хвост
            else:
                range_end = rule_to_min

        # Нормализуем range_end к абсолютным минутам
        # current может быть больше 1440 при бронировании через полночь
        day_offset = (current // 1440) * 1440
        if rule_to_min > rule_from_min:
            abs_range_end = day_offset + rule_to_min
        else:
            if (current % 1440) >= rule_from_min:
                abs_range_end = day_offset + 1440 + rule_to_min
            else:
                abs_range_end = day_offset + rule_to_min

        # Берём минимум: конец тарифа или конец бронирования
        chunk_end = min(abs_range_end, end_minutes)
        minutes_in_range = chunk_end - current

        if minutes_in_range > 0:
            total_price += int(minutes_in_range / 60 * matched_rule.price_per_hour)
            current = chunk_end
        else:
            current += 1

    return total_price


async def calculate_time_based_price_detailed(
    session: AsyncSession,
    employee_id: int,
    start_time: time,
    duration_minutes: int,
    booking_date: date = None
) -> Optional[dict]:
    """Рассчитать стоимость с детализацией по тарифным зонам.

    Возвращает None если тарифов нет.
    Иначе возвращает dict:
        {
            "total": int,
            "segments": [
                {"time_from": "13:00", "time_to": "14:00", "minutes": 60,
                 "price_per_hour": 1000, "subtotal": 1000},
                ...
            ]
        }
    """
    rules = await get_employee_time_pricing(session, employee_id, booking_date=booking_date)
    if not rules:
        return None

    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = start_minutes + duration_minutes
    total_price = 0
    segments = []

    current = start_minutes
    while current < end_minutes:
        matched_rule = None

        for rule in rules:
            rule_from_min = rule.time_from.hour * 60 + rule.time_from.minute
            rule_to_min = rule.time_to.hour * 60 + rule.time_to.minute

            if rule_to_min > rule_from_min:
                if rule_from_min <= (current % 1440) < rule_to_min:
                    matched_rule = rule
                    break
            else:
                if (current % 1440) >= rule_from_min or (current % 1440) < rule_to_min:
                    matched_rule = rule
                    break

        if not matched_rule:
            current += 1
            continue

        rule_from_min = matched_rule.time_from.hour * 60 + matched_rule.time_from.minute
        rule_to_min = matched_rule.time_to.hour * 60 + matched_rule.time_to.minute

        day_offset = (current // 1440) * 1440
        if rule_to_min > rule_from_min:
            abs_range_end = day_offset + rule_to_min
        else:
            if (current % 1440) >= rule_from_min:
                abs_range_end = day_offset + 1440 + rule_to_min
            else:
                abs_range_end = day_offset + rule_to_min

        chunk_end = min(abs_range_end, end_minutes)
        minutes_in_range = chunk_end - current

        if minutes_in_range > 0:
            subtotal = int(minutes_in_range / 60 * matched_rule.price_per_hour)
            total_price += subtotal

            seg_from_h, seg_from_m = (current % 1440) // 60, (current % 1440) % 60
            seg_to_h, seg_to_m = (chunk_end % 1440) // 60, (chunk_end % 1440) % 60

            segments.append({
                "time_from": f"{seg_from_h:02d}:{seg_from_m:02d}",
                "time_to": f"{seg_to_h:02d}:{seg_to_m:02d}",
                "minutes": minutes_in_range,
                "price_per_hour": matched_rule.price_per_hour,
                "subtotal": subtotal,
            })
            current = chunk_end
        else:
            current += 1

    return {"total": total_price, "segments": segments}
