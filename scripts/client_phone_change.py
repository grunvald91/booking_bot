"""Авто точка: найти завтрашнюю запись по слову «Хонда» (только чтение, данные маскируются).

Лог GitHub Actions публичный, поэтому личные данные клиентов не печатаются:
телефон — только маска, имя — только первая буква.
"""
import argparse
import asyncio
from datetime import date

BUSINESS_ID = 16
TARGET_DATE = date(2026, 10, 28)
KEYWORDS = ('хонд', 'honda')


def mask_phone(value):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if not digits:
        return 'нет'
    return f'{digits[:1]}…{digits[-2:]} ({len(digits)} цифр)'


async def run(apply: bool) -> None:
    from sqlalchemy import select, func
    from database.database import async_session_maker
    from database.models import Booking, Service, User

    async with async_session_maker() as db:
        rows = (await db.execute(
            select(Booking, User, Service).join(User, User.id == Booking.client_id).join(Service, Service.id == Booking.service_id)
            .where(Booking.business_id == BUSINESS_ID, Booking.booking_date == TARGET_DATE)
            .order_by(Booking.booking_time))).all()
        print(f'date={TARGET_DATE}; bookings_total={len(rows)}')
        matches = []
        for booking, user, service in rows:
            haystack = {'notes': (booking.notes or '').lower(), 'name': (user.full_name or '').lower(),
                        'username': (user.username or '').lower()}
            where = [k for k, v in haystack.items() if any(w in v for w in KEYWORDS)]
            print(f'booking id={booking.id}; time={booking.booking_time}; status={booking.status}; service={service.name!r}; '
                  f'client_id={user.id}; initial={(user.full_name or "?")[:1]}; phone={mask_phone(user.phone)}; match={where}')
            if where:
                matches.append((booking, user))
        print(f'matches={len(matches)}')
        for booking, user in matches:
            total = (await db.execute(select(func.count()).select_from(Booking).where(Booking.client_id == user.id))).scalar_one()
            print(f'match booking={booking.id}; client_id={user.id}; client_total_bookings={total}; '
                  f'telegram_linked={bool(user.telegram_id and user.telegram_id > 0)}')
        if apply:
            raise RuntimeError('apply is not implemented in this version')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
