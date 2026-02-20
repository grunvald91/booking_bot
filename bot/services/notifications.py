"""
Модуль для отправки уведомлений клиентам, мастерам и владельцам
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import async_session_maker
from database.models import Booking, User, Business, Employee
from database.crud import get_business_owners
from bot.utils.validators import format_date_with_weekday, format_phone
from bot.utils.business_types import get_terminology, is_venue_rental_type


def get_employee_label(business_type: str) -> str:
    """Получить правильный термин для сотрудника в зависимости от типа бизнеса"""
    term = get_terminology(business_type)
    return term.get("employee", "Мастер")


def format_business_phone(phone: str) -> str | None:
    """Форматирует телефон бизнеса для отображения.
    Возвращает None если телефон не начинается с +7 или 8.
    """
    if not phone:
        return None

    # Убираем пробелы и дефисы для проверки
    clean_phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    # Проверяем формат
    if clean_phone.startswith("+7") or clean_phone.startswith("8"):
        return phone  # Возвращаем оригинальный формат

    return None


def get_maps_link(address: str) -> str:
    """Создаёт кликабельную ссылку на Яндекс Карты для адреса."""
    encoded_address = quote(address)
    return f'<a href="https://yandex.ru/maps/?text={encoded_address}">{address}</a>'

logger = logging.getLogger(__name__)


async def send_24h_reminder(bot: Bot, booking: Booking, session: AsyncSession):
    """Отправка напоминания клиенту за 24 часа до записи (для одной записи - legacy)"""
    # Используем новую функцию с группировкой
    await send_grouped_24h_reminder(bot, [booking], session)


async def send_grouped_24h_reminder(bot: Bot, bookings: list, session: AsyncSession):
    """Отправка ОДНОГО напоминания для группы записей (один визит с несколькими услугами)"""
    if not bookings:
        return

    try:
        # Берём данные из первой записи (клиент, бизнес, дата/время одинаковые для группы)
        first_booking = bookings[0]
        client = first_booking.client
        business = first_booking.business

        # Находим основную услугу (с длительностью > 0) и её мастера/помещение
        main_booking = None
        for b in bookings:
            if b.service and b.service.duration_minutes > 0:
                main_booking = b
                break
        if not main_booking:
            main_booking = first_booking

        employee = main_booking.employee

        # Собираем все услуги
        total_duration = 0
        total_price = 0
        services_list = []

        for b in bookings:
            if b.service:
                services_list.append({
                    'name': b.service.name,
                    'duration': b.service.duration_minutes,
                    'price': b.service.price or 0,
                    'is_additional': b.service.is_additional if hasattr(b.service, 'is_additional') else False
                })
                total_duration += b.service.duration_minutes
                total_price += b.service.price or 0

        # Формируем сообщение
        message = f"""
🔔 <b>Напоминание о записи</b>

📅 Дата: {format_date_with_weekday(first_booking.booking_date)}
🕐 Время: {first_booking.booking_time.strftime('%H:%M')}

🏢 {business.name}
"""

        # Если несколько услуг - показываем списком
        if len(services_list) > 1:
            message += "\n💼 Услуги:\n"
            for s in services_list:
                price_str = f" - {s['price']}₽" if s['price'] else ""
                duration_str = f" ({s['duration']} мин)" if s['duration'] > 0 else ""
                message += f"  • {s['name']}{duration_str}{price_str}\n"
            message += f"\n⏱ Общая длительность: {total_duration} мин"
            message += f"\n💰 Общая сумма: {total_price} ₽"
        else:
            # Одна услуга - старый формат
            service = first_booking.service
            message += f"💼 Услуга: {service.name}\n"
            message += f"⏱ Длительность: {service.duration_minutes} мин\n"
            message += f"💰 Цена: {service.price} ₽"

        if employee:
            emp_label = get_employee_label(business.business_type)
            message += f"\n👔 {emp_label}: {employee.name}"

        if business.address:
            message += f"\n\n📍 Адрес: {get_maps_link(business.address)}"

        # Телефон бизнеса для связи
        business_phone = format_business_phone(business.phone)
        if business_phone:
            tel_link = business_phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if tel_link.startswith("8"):
                tel_link = "+7" + tel_link[1:]
            message += f'\n📞 Телефон для связи: <a href="tel:{tel_link}">{business_phone}</a>'

        if business.directions:
            message += f"\n\n🗺 Как добраться:\n{business.directions}"

        message += "\n\n✨ До встречи! Ждём вас! 😊"

        await bot.send_message(
            chat_id=client.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        # Отмечаем что уведомление отправлено для ВСЕХ записей группы
        for b in bookings:
            b.reminder_24h_sent = True
        await session.commit()

        booking_ids = [b.id for b in bookings]
        logger.info(f"Sent grouped 24h reminder for bookings {booking_ids} to user {client.telegram_id}")

    except Exception as e:
        booking_ids = [b.id for b in bookings]
        logger.error(f"Error sending grouped 24h reminder for bookings {booking_ids}: {e}")


async def send_2h_reminder(bot: Bot, booking: Booking, session: AsyncSession):
    """Отправка напоминания клиенту за 2 часа до записи (для одной записи - legacy)"""
    # Используем новую функцию с группировкой
    await send_grouped_2h_reminder(bot, [booking], session)


async def send_grouped_2h_reminder(bot: Bot, bookings: list, session: AsyncSession):
    """Отправка ОДНОГО напоминания за 2 часа для группы записей"""
    if not bookings:
        return

    try:
        first_booking = bookings[0]
        client = first_booking.client
        business = first_booking.business

        # Находим основную услугу и её мастера/помещение
        main_booking = None
        for b in bookings:
            if b.service and b.service.duration_minutes > 0:
                main_booking = b
                break
        if not main_booking:
            main_booking = first_booking

        employee = main_booking.employee

        # Проверяем, было ли отправлено 24ч напоминание (берём из любой записи группы)
        reminder_24h_was_sent = any(b.reminder_24h_sent for b in bookings)

        # Собираем услуги
        total_duration = 0
        total_price = 0
        services_list = []

        for b in bookings:
            if b.service:
                services_list.append({
                    'name': b.service.name,
                    'duration': b.service.duration_minutes,
                    'price': b.service.price or 0
                })
                total_duration += b.service.duration_minutes
                total_price += b.service.price or 0

        # Если уведомление за 24ч не было отправлено - полное уведомление
        if not reminder_24h_was_sent:
            message = f"""
🔔 <b>Напоминание о записи через 2 часа!</b>

📅 Дата: {format_date_with_weekday(first_booking.booking_date)}
🕐 Время: {first_booking.booking_time.strftime('%H:%M')}

🏢 {business.name}
"""
            if len(services_list) > 1:
                message += "\n💼 Услуги:\n"
                for s in services_list:
                    price_str = f" - {s['price']}₽" if s['price'] else ""
                    duration_str = f" ({s['duration']} мин)" if s['duration'] > 0 else ""
                    message += f"  • {s['name']}{duration_str}{price_str}\n"
                message += f"\n⏱ Общая длительность: {total_duration} мин"
                message += f"\n💰 Общая сумма: {total_price} ₽"
            else:
                service = first_booking.service
                message += f"💼 Услуга: {service.name}\n"
                message += f"⏱ Длительность: {service.duration_minutes} мин\n"
                message += f"💰 Цена: {service.price} ₽"

            if employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n👔 {emp_label}: {employee.name}"

            if business.address:
                message += f"\n\n📍 Адрес: {get_maps_link(business.address)}"

            business_phone = format_business_phone(business.phone)
            if business_phone:
                tel_link = business_phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                if tel_link.startswith("8"):
                    tel_link = "+7" + tel_link[1:]
                message += f'\n📞 Телефон для связи: <a href="tel:{tel_link}">{business_phone}</a>'

            if business.directions:
                message += f"\n\n🗺 Как добраться:\n{business.directions}"

            message += "\n\n✨ Скоро встретимся! Ждём вас! 😊"
        else:
            # Краткое напоминание
            message = f"""
⏰ <b>Напоминание: через 2 часа ваша запись!</b>

🕐 Время: {first_booking.booking_time.strftime('%H:%M')}
🏢 {business.name}
"""
            if len(services_list) > 1:
                services_names = ", ".join(s['name'] for s in services_list)
                message += f"💼 {services_names}"
            else:
                message += f"💼 {first_booking.service.name}"

            if business.address:
                message += f"\n📍 Адрес: {get_maps_link(business.address)}"

            business_phone = format_business_phone(business.phone)
            if business_phone:
                tel_link = business_phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                if tel_link.startswith("8"):
                    tel_link = "+7" + tel_link[1:]
                message += f'\n📞 Телефон для связи: <a href="tel:{tel_link}">{business_phone}</a>'

            message += "\n\n✨ Ждём вас! 😊"

        await bot.send_message(
            chat_id=client.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        # Отмечаем для ВСЕХ записей группы
        for b in bookings:
            b.reminder_2h_sent = True
        await session.commit()

        booking_ids = [b.id for b in bookings]
        logger.info(f"Sent grouped 2h reminder for bookings {booking_ids} to user {client.telegram_id}")

    except Exception as e:
        booking_ids = [b.id for b in bookings]
        logger.error(f"Error sending grouped 2h reminder for bookings {booking_ids}: {e}")


async def notify_master_new_booking(bot: Bot, booking: Booking, services_list: Optional[list] = None, is_subscription: bool = False, subscription_name: str = None):
    """Уведомление мастеру о новой записи

    Args:
        bot: Экземпляр бота
        booking: Запись (может быть первой из нескольких)
        services_list: Список услуг [{'name': str, 'duration': int, 'price': int, 'employee_id': int (опционально), 'employee_name': str (опционально)}, ...]
        is_subscription: Запись по абонементу
        subscription_name: Название абонемента
    """
    try:
        client = booking.client

        # Формируем ссылку на Telegram профиль клиента
        client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'

        # Собираем уникальных мастеров и их услуги
        masters_services = {}  # telegram_id -> {'name': str, 'services': []}

        if services_list and len(services_list) > 0:
            for s in services_list:
                emp_id = s.get('employee_id')
                emp_name = s.get('employee_name', 'Мастер')
                emp_telegram_id = s.get('employee_telegram_id')

                if emp_telegram_id:
                    if emp_telegram_id not in masters_services:
                        masters_services[emp_telegram_id] = {'name': emp_name, 'services': []}
                    masters_services[emp_telegram_id]['services'].append(s)
                elif booking.employee and booking.employee.telegram_id:
                    # Если нет информации о мастере в услуге, используем мастера из записи
                    emp_telegram_id = booking.employee.telegram_id
                    if emp_telegram_id not in masters_services:
                        masters_services[emp_telegram_id] = {'name': booking.employee.name, 'services': []}
                    masters_services[emp_telegram_id]['services'].append(s)

            # Если masters_services пустой, но есть мастер в booking
            if not masters_services and booking.employee and booking.employee.telegram_id:
                masters_services[booking.employee.telegram_id] = {
                    'name': booking.employee.name,
                    'services': services_list
                }
        else:
            # Одна услуга (обратная совместимость)
            if booking.employee and booking.employee.telegram_id:
                masters_services[booking.employee.telegram_id] = {
                    'name': booking.employee.name,
                    'services': [{
                        'name': booking.service.name,
                        'duration': booking.service.duration_minutes,
                        'price': booking.service.price
                    }]
                }

        # Отправляем уведомление каждому мастеру
        for master_telegram_id, master_data in masters_services.items():
            master_services = master_data['services']

            message = f"""
🆕 <b>Новая запись!</b>

📅 Дата: {format_date_with_weekday(booking.booking_date)}
🕐 Время: {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

            if client.phone:
                formatted_phone = format_phone(client.phone)
                tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
                message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

            # Показываем услуги этого мастера
            message += "\n💼 Ваши услуги:\n"
            total_duration = 0
            total_price = 0
            for s in master_services:
                price_part = f" - {s['price']}₽" if s.get('price') else ""
                message += f"  • {s['name']} ({s['duration']} мин{price_part})\n"
                total_duration += s['duration']
                if s.get('price'):
                    total_price += s['price']
            message += f"\n⏱ Длительность: {total_duration} мин"
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif total_price > 0:
                message += f"\n💰 Сумма: {total_price}₽"

            if booking.notes:
                message += f"\n\n💬 Комментарий: {booking.notes}"

            try:
                await bot.send_message(
                    chat_id=master_telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                logger.info(f"Notified master {master_telegram_id} about booking {booking.id}")
            except Exception as e:
                logger.error(f"Error notifying master {master_telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Error notifying master about booking {booking.id}: {e}")


async def notify_owner_new_booking(bot: Bot, booking: Booking, services_list: Optional[list] = None, is_subscription: bool = False, subscription_name: str = None):
    """Уведомление владельцу о новой записи

    Args:
        bot: Экземпляр бота
        booking: Запись (может быть первой из нескольких)
        services_list: Список услуг [{'name': str, 'duration': int, 'price': int, 'employee_id': int (опц), 'employee_name': str (опц)}, ...]
        is_subscription: Запись по абонементу
        subscription_name: Название абонемента
    """
    try:
        # Все данные уже подгружены в booking через selectinload
        business = booking.business
        owner = business.owner
        client = booking.client
        employee = booking.employee

        # Формируем ссылку на Telegram профиль клиента
        client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'

        message = f"""
🆕 <b>Новая запись в {business.name}</b>

📅 {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        # Показываем услуги
        if services_list and len(services_list) > 0:
            # Проверяем, есть ли разные мастера для разных услуг
            has_per_service_employees = any(s.get('employee_name') for s in services_list)

            message += "\n💼 Услуги:\n"
            total_price = 0
            for s in services_list:
                price_part = f" - {s['price']}₽" if s.get('price') else ""
                emp_part = f" ({s['employee_name']})" if s.get('employee_name') and has_per_service_employees else ""
                message += f"  • {s['name']}{price_part}{emp_part}\n"
                if s.get('price'):
                    total_price += s['price']
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif total_price > 0:
                message += f"\n💰 Общая сумма: {total_price}₽"

            # Если нет пошагового выбора - показываем одного мастера/помещение
            if not has_per_service_employees and employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"
        else:
            # Одна услуга (обратная совместимость)
            service = booking.service
            message += f"\n💼 Услуга: {service.name}"
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif service.price:
                message += f"\n💰 Сумма: {service.price}₽"
            if employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"

        if booking.notes:
            message += f"\n\n💬 Комментарий: {booking.notes}"

        logger.info(f"Sending notification to owner {owner.telegram_id}: {message[:200]}")

        await bot.send_message(
            chat_id=owner.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        logger.info(f"Notified owner {owner.telegram_id} about booking {booking.id}")

    except Exception as e:
        logger.error(f"Error notifying owner about booking {booking.id}: {e}")


async def notify_owner_cancelled_booking(bot: Bot, booking: Booking):
    """Уведомление владельцу об отмене записи"""
    try:
        # Все данные уже подгружены в booking через selectinload
        business = booking.business
        owner = business.owner
        client = booking.client
        service = booking.service

        # Формируем ссылку на клиента
        if client.telegram_id and client.telegram_id > 0:
            client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'
        else:
            client_link = client.full_name

        message = f"""
❌ <b>Отменена запись в {business.name}</b>

📅 {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        message += f"""
💼 Услуга: {service.name}
💰 Потеря: {service.price}₽
"""

        await bot.send_message(
            chat_id=owner.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        logger.info(f"Notified owner {owner.telegram_id} about cancelled booking {booking.id}")

    except Exception as e:
        logger.error(f"Error notifying owner about cancelled booking {booking.id}: {e}")


async def notify_owner_rescheduled_booking(bot: Bot, booking: Booking, old_date, old_time):
    """Уведомление владельцу и мастеру о переносе записи"""
    try:
        business = booking.business
        owner = business.owner
        client = booking.client
        service = booking.service
        employee = booking.employee

        # Формируем ссылку на клиента
        if client.telegram_id and client.telegram_id > 0:
            client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'
        else:
            client_link = client.full_name

        message = f"""
🔄 <b>Запись перенесена в {business.name}</b>

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        message += f"""
💼 Услуга: {service.name}

📅 <b>Было:</b> {format_date_with_weekday(old_date)} в {old_time.strftime('%H:%M')}
📅 <b>Стало:</b> {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}
"""

        if employee:
            emp_label = get_employee_label(business.business_type)
            message += f"\n👔 {emp_label}: {employee.name}"

        # Уведомляем владельца
        try:
            await bot.send_message(
                chat_id=owner.telegram_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"Notified owner {owner.telegram_id} about rescheduled booking {booking.id}")
        except Exception as e:
            logger.error(f"Error notifying owner about rescheduled booking: {e}")

        # Уведомляем мастера (если есть)
        if employee and employee.telegram_id:
            try:
                await bot.send_message(
                    chat_id=employee.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                logger.info(f"Notified master {employee.telegram_id} about rescheduled booking {booking.id}")
            except Exception as e:
                logger.error(f"Error notifying master about rescheduled booking: {e}")

    except Exception as e:
        logger.error(f"Error notifying about rescheduled booking {booking.id}: {e}")


async def notify_administrator_new_booking(bot: Bot, booking: Booking, services_list: Optional[list] = None, created_by_master: str = None, is_subscription: bool = False, subscription_name: str = None):
    """Уведомление администратору бизнеса о новой записи

    Args:
        bot: Экземпляр бота
        booking: Запись
        services_list: Список услуг [{'name': str, 'duration': int, 'price': int}, ...]
        created_by_master: Имя мастера, который создал запись (если создано мастером)
        is_subscription: Запись по абонементу
        subscription_name: Название абонемента
    """
    try:
        from database.crud import get_business_employees

        business = booking.business
        client = booking.client
        employee = booking.employee

        # Находим всех администраторов бизнеса (включая совмещенные роли)
        async with async_session_maker() as session:
            employees = await get_business_employees(session, business.id)
            administrators = [e for e in employees if e.role in ("administrator", "master_and_admin") and e.telegram_id]

        if not administrators:
            logger.info(f"No administrators with telegram_id for business {business.id}")
            return

        # Формируем ссылку на Telegram профиль клиента
        if client.telegram_id and client.telegram_id > 0:
            client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'
        else:
            client_link = client.full_name

        message = f"""
🆕 <b>Новая запись в {business.name}</b>

📅 {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        # Показываем услуги
        if services_list and len(services_list) > 0:
            # Проверяем, есть ли разные мастера для разных услуг
            has_per_service_employees = any(s.get('employee_name') for s in services_list)

            message += "\n💼 Услуги:\n"
            total_duration = 0
            total_price = 0
            for s in services_list:
                price_part = f" - {s['price']}₽" if s.get('price') else ""
                emp_part = f" ({s['employee_name']})" if s.get('employee_name') and has_per_service_employees else ""
                message += f"  • {s['name']} ({s['duration']} мин{price_part}){emp_part}\n"
                total_duration += s['duration']
                if s.get('price'):
                    total_price += s['price']
            message += f"\n⏱ Общая длительность: {total_duration} мин"
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif total_price > 0:
                message += f"\n💰 Общая сумма: {total_price}₽"

            # Если нет пошагового выбора - показываем одного мастера/помещение
            if not has_per_service_employees and employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"
        else:
            service = booking.service
            message += f"\n💼 Услуга: {service.name}\n"
            message += f"⏱ Длительность: {service.duration_minutes} мин"
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif service.price:
                message += f"\n💰 Цена: {service.price}₽"
            if employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"

        if booking.notes:
            message += f"\n\n💬 Комментарий: {booking.notes}"

        if created_by_master:
            message += f"\n\n📝 <i>Запись создана мастером: {created_by_master}</i>"

        # Отправляем уведомление каждому администратору
        for admin in administrators:
            try:
                await bot.send_message(
                    chat_id=admin.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                logger.info(f"Notified administrator {admin.telegram_id} about booking {booking.id}")
            except Exception as e:
                logger.error(f"Error notifying administrator {admin.telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Error notifying administrators about booking {booking.id}: {e}")


def _group_bookings_by_visit(bookings: list) -> dict:
    """Группировка записей по визиту (клиент + бизнес + дата + время)"""
    groups = {}
    for booking in bookings:
        # Ключ группы: (client_id, business_id, date, time)
        key = (
            booking.client_id,
            booking.business_id,
            booking.booking_date,
            booking.booking_time
        )
        if key not in groups:
            groups[key] = []
        groups[key].append(booking)
    return groups


async def check_and_send_reminders(bot: Bot):
    """Проверка и отправка напоминаний о предстоящих записях (с группировкой по визитам)"""
    try:
        async with async_session_maker() as session:
            now = datetime.now()  # Используем локальное время

            # === Напоминания за 24 часа ===
            time_24h_from_now = now + timedelta(hours=24)
            time_24h_window_start = time_24h_from_now - timedelta(minutes=5)
            time_24h_window_end = time_24h_from_now + timedelta(minutes=5)

            result = await session.execute(
                select(Booking)
                .options(
                    selectinload(Booking.client),
                    selectinload(Booking.business),
                    selectinload(Booking.service),
                    selectinload(Booking.employee)
                )
                .where(Booking.status.in_(["pending", "confirmed"]))
                .where(Booking.reminder_24h_sent == False)
            )
            bookings_24h = list(result.scalars().all())

            # Фильтруем по времени
            bookings_24h_filtered = []
            for booking in bookings_24h:
                booking_datetime = datetime.combine(booking.booking_date, booking.booking_time)
                if time_24h_window_start <= booking_datetime <= time_24h_window_end:
                    bookings_24h_filtered.append(booking)

            # Группируем по визитам и отправляем
            groups_24h = _group_bookings_by_visit(bookings_24h_filtered)
            for group_key, group_bookings in groups_24h.items():
                await send_grouped_24h_reminder(bot, group_bookings, session)

            # === Напоминания за 2 часа ===
            time_2h_from_now = now + timedelta(hours=2)
            time_2h_window_start = time_2h_from_now - timedelta(minutes=5)
            time_2h_window_end = time_2h_from_now + timedelta(minutes=5)

            result = await session.execute(
                select(Booking)
                .options(
                    selectinload(Booking.client),
                    selectinload(Booking.business),
                    selectinload(Booking.service),
                    selectinload(Booking.employee)
                )
                .where(Booking.status.in_(["pending", "confirmed"]))
                .where(Booking.reminder_2h_sent == False)
            )
            bookings_2h = list(result.scalars().all())

            # Фильтруем по времени
            bookings_2h_filtered = []
            for booking in bookings_2h:
                booking_datetime = datetime.combine(booking.booking_date, booking.booking_time)
                if time_2h_window_start <= booking_datetime <= time_2h_window_end:
                    bookings_2h_filtered.append(booking)

            # Группируем по визитам и отправляем
            groups_2h = _group_bookings_by_visit(bookings_2h_filtered)
            for group_key, group_bookings in groups_2h.items():
                await send_grouped_2h_reminder(bot, group_bookings, session)

            logger.info(f"Checked reminders: {len(groups_24h)} visits for 24h, {len(groups_2h)} visits for 2h")

    except Exception as e:
        logger.error(f"Error checking reminders: {e}")


async def auto_complete_bookings():
    """Автоматическое завершение записей после окончания времени услуги"""
    try:
        async with async_session_maker() as session:
            now = datetime.utcnow()  # Используем UTC как в моделях

            # Находим все подтвержденные записи, которые должны быть завершены
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(Booking.status.in_(["pending", "confirmed"]))
            )
            active_bookings = result.scalars().all()

            completed_count = 0
            for booking in active_bookings:
                # Вычисляем время окончания услуги
                booking_datetime = datetime.combine(booking.booking_date, booking.booking_time)
                service_end_time = booking_datetime + timedelta(minutes=booking.service.duration_minutes)

                # Если время услуги прошло, завершаем запись
                if now >= service_end_time:
                    booking.status = "completed"
                    completed_count += 1

            if completed_count > 0:
                await session.commit()
                logger.info(f"Auto-completed {completed_count} bookings")

    except Exception as e:
        logger.error(f"Error auto-completing bookings: {e}")


async def check_and_send_subscription_reminders(bot: Bot):
    """Проверка и отправка напоминаний об истекающих абонементах"""
    try:
        from database.crud import get_expiring_subscriptions, mark_expiry_reminder_sent, get_subscription_remaining

        async with async_session_maker() as session:
            # Получаем абонементы, истекающие в ближайшие 7 дней
            expiring_subscriptions = await get_expiring_subscriptions(session, days_until_expiry=7)

            for client_sub in expiring_subscriptions:
                # Проверяем, осталось ли менее 25% времени
                from datetime import datetime
                now = datetime.utcnow()
                total_days = client_sub.subscription.validity_days
                days_left = (client_sub.expires_at - now).days

                # Отправляем напоминание если осталось менее 25% времени или менее 7 дней
                should_remind = days_left <= 7 or (days_left / total_days) < 0.25

                if should_remind:
                    await send_subscription_expiry_reminder(bot, client_sub, session)
                    await mark_expiry_reminder_sent(session, client_sub.id)

            logger.info(f"Checked subscription reminders: {len(expiring_subscriptions)} expiring")

    except Exception as e:
        logger.error(f"Error checking subscription reminders: {e}")


async def send_subscription_expiry_reminder(bot: Bot, client_subscription, session):
    """Отправка напоминания об истечении абонемента"""
    try:
        from database.crud import get_subscription_remaining

        client = client_subscription.client
        subscription = client_subscription.subscription
        business = client_subscription.business

        days_left = (client_subscription.expires_at - datetime.utcnow()).days

        # Получаем остаток услуг
        remaining = await get_subscription_remaining(session, client_subscription.id)

        remaining_text = ""
        total_remaining = 0
        for service_id, info in remaining.items():
            if info['remaining'] > 0:
                remaining_text += f"  • {info['service_name']}: {info['remaining']} шт.\n"
                total_remaining += info['remaining']

        message = f"""
⚠️ <b>Абонемент скоро истекает!</b>

🎫 {subscription.name}
🏢 {business.name}

⏰ Осталось дней: <b>{days_left}</b>
📅 Истекает: {client_subscription.expires_at.strftime('%d.%m.%Y')}
"""

        if remaining_text:
            message += f"\n📋 <b>Неиспользованные услуги:</b>\n{remaining_text}"
            if total_remaining > 0:
                message += f"\n💡 Не забудьте использовать оставшиеся {total_remaining} услуг до истечения срока!"

        await bot.send_message(
            chat_id=client.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        logger.info(f"Sent subscription expiry reminder to user {client.telegram_id} for subscription {client_subscription.id}")

    except Exception as e:
        logger.error(f"Error sending subscription expiry reminder: {e}")


async def notify_business_owners(bot: Bot, business_id: int, message: str, session: AsyncSession = None):
    """
    Отправить уведомление всем владельцам бизнеса.

    Args:
        bot: Экземпляр бота
        business_id: ID бизнеса
        message: Текст сообщения (HTML формат)
        session: Сессия базы данных (опционально, создастся автоматически)
    """
    try:
        if session:
            owners = await get_business_owners(session, business_id)
            for owner in owners:
                try:
                    await bot.send_message(
                        chat_id=owner.telegram_id,
                        text=message,
                        parse_mode="HTML"
                    )
                    logger.info(f"Notified owner {owner.telegram_id} for business {business_id}")
                except Exception as e:
                    logger.error(f"Error notifying owner {owner.telegram_id}: {e}")
        else:
            async with async_session_maker() as session:
                owners = await get_business_owners(session, business_id)
                for owner in owners:
                    try:
                        await bot.send_message(
                            chat_id=owner.telegram_id,
                            text=message,
                            parse_mode="HTML"
                        )
                        logger.info(f"Notified owner {owner.telegram_id} for business {business_id}")
                    except Exception as e:
                        logger.error(f"Error notifying owner {owner.telegram_id}: {e}")
    except Exception as e:
        logger.error(f"Error in notify_business_owners for business {business_id}: {e}")


async def notify_all_owners_new_booking(bot: Bot, booking: Booking, services_list: Optional[list] = None, is_subscription: bool = False, subscription_name: str = None):
    """
    Уведомление ВСЕМ владельцам бизнеса о новой записи.
    Замена notify_owner_new_booking для поддержки множественных владельцев.
    """
    try:
        business = booking.business
        client = booking.client
        employee = booking.employee

        # Формируем ссылку на Telegram профиль клиента
        client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'

        message = f"""
🆕 <b>Новая запись в {business.name}</b>

📅 {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        # Показываем услуги
        if services_list and len(services_list) > 0:
            has_per_service_employees = any(s.get('employee_name') for s in services_list)

            message += "\n💼 Услуги:\n"
            total_price = 0
            for s in services_list:
                price_part = f" - {s['price']}₽" if s.get('price') else ""
                emp_part = f" ({s['employee_name']})" if s.get('employee_name') and has_per_service_employees else ""
                message += f"  • {s['name']}{price_part}{emp_part}\n"
                if s.get('price'):
                    total_price += s['price']
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif total_price > 0:
                message += f"\n💰 Общая сумма: {total_price}₽"

            if not has_per_service_employees and employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"
        else:
            service = booking.service
            message += f"\n💼 Услуга: {service.name}"
            if is_subscription and subscription_name:
                message += f"\n🎫 <b>Оплачено по абонементу: {subscription_name}</b>"
            elif service.price:
                message += f"\n💰 Сумма: {service.price}₽"
            if employee:
                emp_label = get_employee_label(business.business_type)
                message += f"\n\n👔 {emp_label}: {employee.name}"

        if booking.notes:
            message += f"\n\n💬 Комментарий: {booking.notes}"

        # Отправляем всем владельцам
        await notify_business_owners(bot, business.id, message)

        logger.info(f"Notified all owners about booking {booking.id}")

    except Exception as e:
        logger.error(f"Error notifying all owners about booking {booking.id}: {e}")


async def notify_all_owners_cancelled_booking(bot: Bot, booking: Booking):
    """Уведомление всем владельцам об отмене записи"""
    try:
        business = booking.business
        client = booking.client
        service = booking.service

        # Формируем ссылку на клиента
        if client.telegram_id and client.telegram_id > 0:
            client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'
        else:
            client_link = client.full_name

        message = f"""
❌ <b>Отменена запись в {business.name}</b>

📅 {format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}

👤 Клиент: {client_link}
"""

        if client.phone:
            formatted_phone = format_phone(client.phone)
            tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
            message += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

        message += f"""
💼 Услуга: {service.name}
💰 Потеря: {service.price}₽
"""

        await notify_business_owners(bot, business.id, message)

        logger.info(f"Notified all owners about cancelled booking {booking.id}")

    except Exception as e:
        logger.error(f"Error notifying all owners about cancelled booking {booking.id}: {e}")
