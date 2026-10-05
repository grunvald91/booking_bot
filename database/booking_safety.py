"""Central booking concurrency and overlap protection.

Every write path that reserves a concrete employee/resource should use these
helpers before INSERT/UPDATE. PostgreSQL advisory transaction locks serialize
concurrent requests even when the target slot is currently empty; interval
checks then reject overlaps. The database exclusion constraint is the final
backstop.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Booking, Service


ACTIVE_BOOKING_STATUSES = (
    "pending",
    "confirmed",
    "pending_prepayment",
    "prepayment_sent",
    "prepayment_confirmed",
)


class BookingConflictError(ValueError):
    """Requested resource interval overlaps an active booking."""


def _expanded_lock_dates(dates: Iterable[date]) -> list[date]:
    """Lock target days plus neighbours for cross-midnight safety."""
    result: set[date] = set()
    for day in dates:
        result.add(day - timedelta(days=1))
        result.add(day)
        result.add(day + timedelta(days=1))
    return sorted(result)


async def lock_resource_days(
    session: AsyncSession,
    employee_id: Optional[int],
    dates: Iterable[date],
) -> None:
    """Serialize booking writes for a resource/date window.

    A row lock on existing bookings is insufficient when the slot is empty:
    two transactions can both see zero rows. PostgreSQL transaction-scoped
    advisory locks give us a stable lock key even before any booking row exists.

    Locks are acquired in sorted date order to avoid deadlocks for recurring
    bookings that touch several days.
    """
    if not employee_id:
        return

    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        # Unit tests may run on SQLite. The database exclusion constraint is
        # PostgreSQL-specific too; tests still exercise interval logic.
        return

    for lock_date in _expanded_lock_dates(dates):
        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "CAST(:resource_id AS INTEGER), CAST(:day_key AS INTEGER))"
            ),
            {
                "resource_id": int(employee_id),
                "day_key": int(lock_date.toordinal()),
            },
        )


def intervals_overlap(
    start: datetime,
    end: datetime,
    other_start: datetime,
    other_end: datetime,
) -> bool:
    """Half-open interval overlap: touching endpoints are not a conflict."""
    return start < other_end and other_start < end


def booking_resource_duration(booking: Booking) -> int:
    """Return the immutable resource duration snapshot for a booking."""
    snapshot = getattr(booking, "resource_duration_minutes", None)
    if snapshot is not None:
        return max(0, int(snapshot))

    rental_duration = getattr(booking, "duration_minutes", None)
    if rental_duration is not None:
        return max(0, int(rental_duration))

    service = getattr(booking, "service", None)
    if service is not None and getattr(service, "duration_minutes", None) is not None:
        return max(0, int(service.duration_minutes))

    return 30


def service_resource_duration(service: Optional[Service]) -> int:
    if service is None:
        return 30
    return max(0, int(service.duration_minutes or 0))


def service_occupies_resource(service: Optional[Service]) -> bool:
    if service is None:
        return True
    return not bool(getattr(service, "is_additional", False)) and service_resource_duration(service) > 0


async def resource_overlap_exists(
    session: AsyncSession,
    *,
    employee_id: Optional[int],
    booking_date: date,
    booking_time: time,
    duration_minutes: int,
    exclude_booking_ids: Sequence[int] | None = None,
    acquire_lock: bool = True,
) -> bool:
    """Check whether a resource interval overlaps any active booking."""
    if not employee_id or duration_minutes <= 0:
        return False

    if acquire_lock:
        await lock_resource_days(session, employee_id, [booking_date])

    check_dates = [
        booking_date - timedelta(days=1),
        booking_date,
        booking_date + timedelta(days=1),
    ]
    filters = [
        Booking.employee_id == employee_id,
        Booking.booking_date.in_(check_dates),
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        Booking.occupies_resource.is_(True),
    ]
    if exclude_booking_ids:
        filters.append(Booking.id.notin_(list(exclude_booking_ids)))

    result = await session.execute(
        select(Booking)
        .where(and_(*filters))
        .options(selectinload(Booking.service))
    )
    existing_bookings = result.scalars().all()

    requested_start = datetime.combine(booking_date, booking_time)
    requested_end = requested_start + timedelta(minutes=duration_minutes)

    for existing in existing_bookings:
        existing_duration = booking_resource_duration(existing)
        if existing_duration <= 0:
            continue
        existing_start = datetime.combine(existing.booking_date, existing.booking_time)
        existing_end = existing_start + timedelta(minutes=existing_duration)
        if intervals_overlap(requested_start, requested_end, existing_start, existing_end):
            return True

    return False


async def ensure_resource_available(
    session: AsyncSession,
    *,
    employee_id: Optional[int],
    booking_date: date,
    booking_time: time,
    duration_minutes: int,
    exclude_booking_ids: Sequence[int] | None = None,
    acquire_lock: bool = True,
) -> None:
    if await resource_overlap_exists(
        session,
        employee_id=employee_id,
        booking_date=booking_date,
        booking_time=booking_time,
        duration_minutes=duration_minutes,
        exclude_booking_ids=exclude_booking_ids,
        acquire_lock=acquire_lock,
    ):
        raise BookingConflictError(
            f"Resource is already booked for {booking_date.isoformat()} "
            f"{booking_time.strftime('%H:%M')}"
        )


async def busy_resource_intervals(
    session: AsyncSession,
    *,
    employee_id: int,
    dates: Iterable[date],
) -> list[tuple[datetime, datetime]]:
    """Return active occupied intervals for slot rendering/read-only checks."""
    days = sorted(set(dates))
    if not days:
        return []
    expanded = _expanded_lock_dates(days)
    result = await session.execute(
        select(Booking)
        .where(
            Booking.employee_id == employee_id,
            Booking.booking_date.in_(expanded),
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.occupies_resource.is_(True),
        )
        .options(selectinload(Booking.service))
    )
    intervals: list[tuple[datetime, datetime]] = []
    for booking in result.scalars().all():
        duration = booking_resource_duration(booking)
        if duration <= 0:
            continue
        start = datetime.combine(booking.booking_date, booking.booking_time)
        intervals.append((start, start + timedelta(minutes=duration)))
    return intervals
