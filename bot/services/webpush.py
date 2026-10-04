"""Web Push transport for ServGo client reminders."""
import json
import logging
import os
from datetime import datetime
from typing import Iterable

from pywebpush import WebPushException, webpush_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Booking, PushSubscription

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
