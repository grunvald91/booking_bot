"""Immediate booking event notifications for Telegram and PWA.

Scheduled reminders are configurable. Immediate lifecycle events are not:
a newly created/confirmed booking must reach the client and everybody involved.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import date, time
from typing import Iterable, Optional, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Booking, PushSubscription
from bot.services.webpush import (
    resolve_staff_notification_targets,
    send_webpush_to_subscriptions,
)

logger = logging.getLogger(__name__)


async def _load_bookings(
    session: AsyncSession,
    bookings: Sequence[Booking] | Sequence[int],
) -> list[Booking]:
    if not bookings:
        return []
    first = bookings[0]
    if isinstance(first, Booking):
        ids = [int(b.id) for b in bookings if getattr(b, "id", None)]
    else:
        ids = [int(value) for value in bookings]
    if not ids:
        return []

    result = await session.execute(
        select(Booking)
        .where(Booking.id.in_(ids))
        .options(
            selectinload(Booking.client),
            selectinload(Booking.business),
            selectinload(Booking.service),
            selectinload(Booking.employee),
        )
        .order_by(Booking.booking_date, Booking.booking_time, Booking.id)
    )
    by_id = {booking.id: booking for booking in result.scalars().all()}
    return [by_id[booking_id] for booking_id in ids if booking_id in by_id]


def _services_text(bookings: Iterable[Booking]) -> str:
    names: list[str] = []
    for booking in bookings:
        service = getattr(booking, "service", None)
        if service and service.name and service.name not in names:
            names.append(service.name)
    return ", ".join(names) or "Запись"


def _staff_message(
    bookings: list[Booking],
    event_kind: str,
    *,
    old_date: Optional[date] = None,
    old_time: Optional[time] = None,
) -> str:
    first = bookings[0]
    business = first.business
    client = first.client
    employee = first.employee
    services = _services_text(bookings)

    if event_kind == "created":
        header = "🆕 <b>Новая запись</b>"
    elif event_kind == "prepayment_confirmed":
        header = "✅ <b>Запись подтверждена после предоплаты</b>"
    elif event_kind == "cancelled":
        header = "❌ <b>Запись отменена</b>"
    elif event_kind == "rescheduled":
        header = "🔄 <b>Запись перенесена</b>"
    elif event_kind == "prepayment_sent":
        header = "💳 <b>Клиент отправил предоплату</b>"
    elif event_kind == "rental_request":
        header = "🛥 <b>Новая заявка на аренду</b>"
    else:
        header = "🔔 <b>Изменение записи</b>"

    text = (
        f"{header}\n\n"
        f"🏢 {html.escape(business.name if business else 'ServGo')}\n"
        f"📅 {first.booking_date.strftime('%d.%m.%Y')} в {first.booking_time.strftime('%H:%M')}\n"
        f"💼 {html.escape(services)}\n"
    )
    if employee:
        text += f"👔 {html.escape(employee.name)}\n"
    if client:
        text += f"👤 {html.escape(client.full_name or 'Клиент')}\n"
        if client.phone:
            text += f"📱 {html.escape(client.phone)}\n"
    if event_kind == "rescheduled" and old_date and old_time:
        text += f"\nБыло: {old_date.strftime('%d.%m.%Y')} в {old_time.strftime('%H:%M')}\n"
    if event_kind == "prepayment_sent":
        text += "\nОткройте ServGo и подтвердите получение оплаты."
    elif event_kind in ("created", "prepayment_confirmed", "rental_request"):
        text += "\nОткройте расписание ServGo для деталей."
    return text


def _client_message(
    bookings: list[Booking],
    event_kind: str,
    *,
    old_date: Optional[date] = None,
    old_time: Optional[time] = None,
) -> str:
    first = bookings[0]
    business = first.business
    employee = first.employee
    services = _services_text(bookings)

    if event_kind == "created":
        header = "✅ <b>Запись создана!</b>"
    elif event_kind == "prepayment_confirmed":
        header = "✅ <b>Запись подтверждена!</b>"
    elif event_kind == "cancelled":
        header = "❌ <b>Запись отменена</b>"
    elif event_kind == "rescheduled":
        header = "🔄 <b>Запись перенесена</b>"
    else:
        header = "🔔 <b>Статус записи обновлён</b>"

    text = (
        f"{header}\n\n"
        f"🏢 {html.escape(business.name if business else 'ServGo')}\n"
        f"📅 {first.booking_date.strftime('%d.%m.%Y')} в {first.booking_time.strftime('%H:%M')}\n"
        f"💼 {html.escape(services)}\n"
    )
    if employee:
        text += f"👤 {html.escape(employee.name)}\n"
    if event_kind == "rescheduled" and old_date and old_time:
        text += f"\nБыло: {old_date.strftime('%d.%m.%Y')} в {old_time.strftime('%H:%M')}\n"
    if business and business.address:
        text += f"📍 {html.escape(business.address)}\n"
    return text


async def _send_telegram_messages(
    telegram_ids: Iterable[int],
    text: str,
    *,
    reply_markup: Optional[dict] = None,
) -> int:
    token = os.getenv("BOT_TOKEN", "").strip()
    targets = sorted({int(value) for value in telegram_ids if value and int(value) > 0})
    if not token or ":" not in token or not targets:
        return 0

    sent = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for telegram_id in targets:
            payload = {
                "chat_id": telegram_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            try:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=payload,
                )
                if response.status_code == 200:
                    sent += 1
                else:
                    logger.warning(
                        "Telegram booking event failed target=%s status=%s",
                        telegram_id,
                        response.status_code,
                    )
            except Exception as exc:
                logger.warning("Telegram booking event failed target=%s: %s", telegram_id, exc)
    return sent


async def _send_push_to_users(
    session: AsyncSession,
    user_ids: Iterable[int],
    payload: dict,
) -> tuple[int, int]:
    ids = sorted({int(value) for value in user_ids if value})
    if not ids:
        return 0, 0
    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(ids),
            PushSubscription.is_active == True,
        )
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        return 0, 0
    sent = await send_webpush_to_subscriptions(subscriptions, payload, session)
    return sent, len(subscriptions)


def _event_push_payload(
    bookings: list[Booking],
    event_kind: str,
    *,
    staff: bool,
) -> dict:
    first = bookings[0]
    business_name = first.business.name if first.business else "ServGo"
    client_name = first.client.full_name if first.client else "Клиент"
    service_names = _services_text(bookings)
    when = f"{first.booking_date.strftime('%d.%m')} · {first.booking_time.strftime('%H:%M')}"

    staff_titles = {
        "created": "🆕 Новая запись",
        "prepayment_confirmed": "✅ Запись подтверждена",
        "cancelled": "❌ Запись отменена",
        "rescheduled": "🔄 Запись перенесена",
        "prepayment_sent": "💳 Клиент отправил предоплату",
        "rental_request": "🛥 Новая заявка на аренду",
    }
    client_titles = {
        "created": "✅ Запись создана",
        "prepayment_confirmed": "✅ Запись подтверждена",
        "cancelled": "❌ Запись отменена",
        "rescheduled": "🔄 Запись перенесена",
    }

    if staff:
        title = staff_titles.get(event_kind, "ServGo · запись обновлена")
        body = f"{client_name} · {when} · {service_names}"
        url = "/admin/schedule"
        tag_prefix = "staff"
    else:
        title = client_titles.get(event_kind, "ServGo · статус записи")
        body = f"{business_name} · {when} · {service_names}"
        url = f"/b/{first.notify_token}" if first.notify_token else "/my"
        tag_prefix = "client"

    return {
        "title": title,
        "body": body,
        "url": url,
        "booking_id": first.id,
        "tag": f"servgo-{tag_prefix}-{event_kind}-{first.id}",
    }


async def notify_booking_event(
    session: AsyncSession,
    bookings: Sequence[Booking] | Sequence[int],
    event_kind: str,
    *,
    notify_client: bool = True,
    notify_staff: bool = True,
    staff_owners_only: bool = False,
    telegram_client: bool = True,
    telegram_staff: bool = True,
    push_client: bool = True,
    push_staff: bool = True,
    old_date: Optional[date] = None,
    old_time: Optional[time] = None,
    staff_reply_markup: Optional[dict] = None,
) -> dict:
    """Deliver one immediate booking lifecycle event across available channels."""
    loaded = await _load_bookings(session, bookings)
    if not loaded:
        return {"telegram_client": 0, "telegram_staff": 0, "push_client": 0, "push_staff": 0}

    first = loaded[0]
    result = {
        "telegram_client": 0,
        "telegram_staff": 0,
        "push_client": 0,
        "push_staff": 0,
        "push_client_targets": 0,
        "push_staff_targets": 0,
    }

    if notify_staff:
        staff_user_ids, staff_telegram_ids = await resolve_staff_notification_targets(
            loaded,
            session,
            respect_business_preferences=False,
            owners_only=staff_owners_only,
        )
        if telegram_staff:
            result["telegram_staff"] = await _send_telegram_messages(
                staff_telegram_ids,
                _staff_message(loaded, event_kind, old_date=old_date, old_time=old_time),
                reply_markup=staff_reply_markup,
            )
        if push_staff:
            sent, targets = await _send_push_to_users(
                session,
                staff_user_ids,
                _event_push_payload(loaded, event_kind, staff=True),
            )
            result["push_staff"] = sent
            result["push_staff_targets"] = targets

    if notify_client and event_kind != "prepayment_sent":
        client = first.client
        if client is not None:
            if telegram_client and client.telegram_id and int(client.telegram_id) > 0:
                result["telegram_client"] = await _send_telegram_messages(
                    [int(client.telegram_id)],
                    _client_message(loaded, event_kind, old_date=old_date, old_time=old_time),
                )
            if push_client:
                sent, targets = await _send_push_to_users(
                    session,
                    [first.client_id],
                    _event_push_payload(loaded, event_kind, staff=False),
                )
                result["push_client"] = sent
                result["push_client_targets"] = targets

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info(
        "Booking event kind=%s booking=%s delivery=%s",
        event_kind,
        first.id,
        result,
    )
    return result
