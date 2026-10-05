"""Web Push transport for ServGo client and staff reminders."""
import json
import logging
import os
from datetime import datetime
from typing import Iterable

from pywebpush import WebPushException, webpush_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Booking, BusinessOwner, Employee, PushSubscription, User

logger = logging.getLogger(__name__)


def webpush_configured() -> bool:
    return bool(
        os.getenv("VAPID_PUBLIC_KEY", "").strip()
        and os.getenv("VAPID_PRIVATE_KEY", "").strip()
        and os.getenv("VAPID_SUBJECT", "").strip()
    )


def _status_from_exception(exc: WebPushException) -> int | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "status", None) or getattr(response, "status_code", None)


async def send_webpush_to_subscriptions(
    subscriptions: Iterable[PushSubscription],
    payload: dict,
    session: AsyncSession,
    ttl: int = 86400,
) -> int:
    if not webpush_configured():
        return 0

    private_key = os.environ["VAPID_PRIVATE_KEY"].strip()
    subject = os.environ["VAPID_SUBJECT"].strip()
    sent = 0

    for subscription in subscriptions:
        try:
            await webpush_async(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                ttl=ttl,
                timeout=10,
            )
            subscription.last_success_at = datetime.utcnow()
            subscription.failure_count = 0
            subscription.updated_at = datetime.utcnow()
            sent += 1
        except WebPushException as exc:
            status = _status_from_exception(exc)
            subscription.failure_count = (subscription.failure_count or 0) + 1
            subscription.updated_at = datetime.utcnow()
            if status in (404, 410):
                subscription.is_active = False
            logger.warning(
                "Web Push failed for subscription %s status=%s: %s",
                subscription.id,
                status,
                exc,
            )
        except Exception as exc:
            subscription.failure_count = (subscription.failure_count or 0) + 1
            subscription.updated_at = datetime.utcnow()
            logger.warning("Web Push failed for subscription %s: %s", subscription.id, exc)

    await session.flush()
    return sent


async def send_booking_webpush(
    bookings: list[Booking],
    session: AsyncSession,
    reminder_kind: str,
) -> int:
    if not bookings:
        return 0

    first = bookings[0]
    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == first.client_id,
            PushSubscription.is_active == True,
        )
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        return 0

    business_name = first.business.name if first.business else "ServGo"
    services = ", ".join(
        b.service.name for b in bookings if getattr(b, "service", None)
    ) or "Запись"
    time_text = first.booking_time.strftime("%H:%M")

    if reminder_kind == "2h":
        title = "⏰ Через 2 часа ваша запись"
        body = f"{business_name} · {time_text} · {services}"
    else:
        title = "🔔 Напоминание о записи"
        body = f"{business_name} · {first.booking_date.strftime('%d.%m.%Y')} в {time_text} · {services}"

    target = f"/b/{first.notify_token}" if first.notify_token else "/my"
    payload = {
        "title": title,
        "body": body,
        "url": target,
        "booking_id": first.id,
        "tag": f"servgo-booking-{first.id}-{reminder_kind}",
    }

    return await send_webpush_to_subscriptions(subscriptions, payload, session)

async def send_booking_status_webpush(
    bookings: list[Booking],
    session: AsyncSession,
    status_kind: str,
) -> int:
    """Send an immediate client push when payment/booking status changes."""
    if not bookings:
        return 0

    first = bookings[0]
    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == first.client_id,
            PushSubscription.is_active == True,
        )
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        return 0

    business_name = first.business.name if first.business else "ServGo"
    time_text = first.booking_time.strftime("%H:%M")

    if status_kind == "prepayment_confirmed":
        title = "✅ Предоплата подтверждена"
        body = f"{business_name} · запись подтверждена на {first.booking_date.strftime('%d.%m.%Y')} в {time_text}"
    elif status_kind == "prepayment_rejected":
        title = "❌ Предоплата не подтверждена"
        body = f"{business_name} · проверьте оплату и реквизиты"
    else:
        title = "ServGo · статус записи обновлён"
        body = f"{business_name} · {first.booking_date.strftime('%d.%m.%Y')} в {time_text}"

    target = f"/b/{first.notify_token}" if first.notify_token else "/my"
    payload = {
        "title": title,
        "body": body,
        "url": target,
        "booking_id": first.id,
        "tag": f"servgo-booking-{first.id}-{status_kind}",
    }
    return await send_webpush_to_subscriptions(subscriptions, payload, session)

async def resolve_staff_notification_targets(
    bookings: list[Booking],
    session: AsyncSession,
    *,
    respect_business_preferences: bool = True,
    owners_only: bool = False,
) -> tuple[set[int], set[int]]:
    """Resolve ServGo user IDs (PWA) and Telegram IDs for staff recipients.

    For scheduled reminders the per-business recipient toggles are respected.
    Immediate booking events deliberately bypass those toggles because a new
    confirmed booking must always reach everybody involved.
    """
    if not bookings:
        return set(), set()

    first = bookings[0]
    business = first.business
    if business is None:
        return set(), set()

    include_owners = True
    include_masters = not owners_only
    include_admins = not owners_only
    if respect_business_preferences:
        include_owners = bool(getattr(business, "staff_notify_owners", True))
        include_masters = bool(getattr(business, "staff_notify_masters", True)) and not owners_only
        include_admins = bool(getattr(business, "staff_notify_admins", True)) and not owners_only

    user_ids: set[int] = set()
    telegram_ids: set[int] = set()

    if include_owners:
        if getattr(business, "owner_id", None):
            user_ids.add(int(business.owner_id))
        owner_rows = await session.execute(
            select(BusinessOwner.user_id).where(BusinessOwner.business_id == first.business_id)
        )
        user_ids.update(int(row[0]) for row in owner_rows.all())

    if include_masters:
        telegram_ids.update(
            int(b.employee.telegram_id)
            for b in bookings
            if getattr(b, "employee", None) is not None
            and getattr(b.employee, "telegram_id", None)
            and int(b.employee.telegram_id) > 0
        )

    if include_admins:
        admin_result = await session.execute(
            select(Employee).where(
                Employee.business_id == first.business_id,
                Employee.is_active == True,
                Employee.role.in_(["administrator", "master_and_admin"]),
                Employee.telegram_id.is_not(None),
            )
        )
        admins = list(admin_result.scalars().all())
        duty_admins: list[Employee] = []
        booking_date = first.booking_date
        booking_date_iso = booking_date.isoformat()
        for admin in admins:
            on_duty = getattr(admin, "on_duty_date", None) == booking_date
            schedule_raw = getattr(admin, "duty_schedule", None)
            if schedule_raw:
                try:
                    schedule = json.loads(schedule_raw) if isinstance(schedule_raw, str) else schedule_raw
                except (json.JSONDecodeError, TypeError):
                    schedule = []
                if isinstance(schedule, list) and booking_date_iso in schedule:
                    on_duty = True
            if on_duty:
                duty_admins.append(admin)

        selected_admins = duty_admins or admins
        telegram_ids.update(
            int(admin.telegram_id)
            for admin in selected_admins
            if admin.telegram_id and int(admin.telegram_id) > 0
        )

    # Owners are stored by user_id, so collect their Telegram IDs as well.
    if user_ids:
        owners_users = await session.execute(
            select(User.id, User.telegram_id).where(User.id.in_(user_ids))
        )
        for user_id, telegram_id in owners_users.all():
            if telegram_id and int(telegram_id) > 0:
                telegram_ids.add(int(telegram_id))

    # Masters/admins are stored by Telegram ID; resolve matching ServGo users
    # so PWA pushes go to their authenticated devices too.
    if telegram_ids:
        staff_users = await session.execute(
            select(User.id).where(User.telegram_id.in_(telegram_ids))
        )
        user_ids.update(int(row[0]) for row in staff_users.all())

    return user_ids, telegram_ids


async def send_staff_booking_webpush(
    bookings: list[Booking],
    session: AsyncSession,
    reminder_slot: str,
    hours_before: int,
) -> tuple[int, int]:
    """Send upcoming-visit push to business owners and assigned masters.

    Returns (sent_count, target_subscription_count). Masters become eligible
    once they have authenticated in ServGo with the same Telegram account and
    enabled Web Push; owners are ordinary ServGo users already.
    """
    if not bookings:
        return 0, 0

    first = bookings[0]
    business = first.business
    if business is None:
        return 0, 0

    user_ids, _ = await resolve_staff_notification_targets(
        bookings,
        session,
        respect_business_preferences=True,
    )
    if not user_ids:
        return 0, 0

    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(user_ids),
            PushSubscription.is_active == True,
        )
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        return 0, 0

    service_names = ", ".join(
        dict.fromkeys(
            b.service.name for b in bookings if getattr(b, "service", None)
        )
    ) or "Запись"
    client_name = (
        first.client.full_name
        if getattr(first, "client", None) is not None
        else "Клиент"
    )
    time_text = first.booking_time.strftime("%H:%M")

    if hours_before <= 3:
        title = f"⏰ Через {hours_before} ч клиент"
        body = f"{client_name} · {time_text} · {service_names}"
    else:
        title = f"📅 Запись через {hours_before} ч"
        body = (
            f"{client_name} · {first.booking_date.strftime('%d.%m.%Y')} "
            f"в {time_text} · {service_names}"
        )

    payload = {
        "title": title,
        "body": body,
        "url": "/",
        "booking_id": first.id,
        "tag": f"servgo-staff-booking-{first.id}-{reminder_slot}",
    }
    sent = await send_webpush_to_subscriptions(subscriptions, payload, session)
    return sent, len(subscriptions)

