"""
Система уведомлений и напоминаний
"""
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot

from database import async_session_maker
from database.crud import get_pending_reminders, mark_reminder_sent


async def send_reminder(bot: Bot, booking):
    """Отправить напоминание о записи"""
    try:
        # Формируем кликабельный телефон (Telegram автоматически делает его ссылкой)
        phone_text = ""
        if booking.business.phone:
            # Убираем все символы кроме цифр и +
            clean_phone = ''.join(c for c in booking.business.phone if c.isdigit() or c == '+')
            # Если номер не начинается с +, добавляем +7 для России
            if not clean_phone.startswith('+'):
                clean_phone = '+7' + clean_phone.lstrip('78')
            phone_text = f'📞 Телефон: <a href="tel:{clean_phone}">{booking.business.phone}</a>'

        # Формируем кликабельный адрес (ссылка на Яндекс.Карты)
        address_text = ""
        if booking.business.address:
            # Кодируем адрес для URL
            from urllib.parse import quote
            encoded_address = quote(booking.business.address)
            yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
            address_text = f'📍 Адрес: <a href="{yandex_maps_url}">{booking.business.address}</a> (открыть на карте)'

        # Формируем текст напоминания
        reminder_text = f"""
🔔 <b>Напоминание о записи</b>

Завтра у вас запись:
📅 Дата: {booking.booking_date.strftime('%d.%m.%Y')}
🕐 Время: {booking.booking_time.strftime('%H:%M')}
🏢 Заведение: {booking.business.name}
💼 Услуга: {booking.service.name}

{address_text}
{phone_text}

Ждем вас!
"""

        # Отправляем клиенту
        await bot.send_message(
            chat_id=booking.client.telegram_id,
            text=reminder_text,
            parse_mode="HTML",
            disable_web_page_preview=True  # Отключаем превью ссылок
        )

        # Отмечаем, что напоминание отправлено
        async with async_session_maker() as session:
            await mark_reminder_sent(session, booking.id)

    except Exception as e:
        print(f"Ошибка отправки напоминания для записи {booking.id}: {e}")


async def check_and_send_reminders(bot: Bot):
    """Проверить и отправить все необходимые напоминания"""
    async with async_session_maker() as session:
        # Получаем записи, для которых нужно отправить напоминание
        bookings = await get_pending_reminders(session)

        tomorrow = datetime.now().date() + timedelta(days=1)

        # Фильтруем записи на завтра
        tomorrow_bookings = [b for b in bookings if b.booking_date == tomorrow]

        for booking in tomorrow_bookings:
            await send_reminder(bot, booking)
            await asyncio.sleep(0.5)  # Небольшая задержка между отправками


async def notification_scheduler(bot: Bot):
    """
    Планировщик для периодической проверки и отправки уведомлений
    Запускается в фоне
    """
    while True:
        try:
            # Проверяем каждый час
            await check_and_send_reminders(bot)
            await asyncio.sleep(3600)  # 1 час
        except Exception as e:
            print(f"Ошибка в планировщике уведомлений: {e}")
            await asyncio.sleep(300)  # При ошибке ждем 5 минут и пробуем снова
