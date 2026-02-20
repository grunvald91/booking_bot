"""
Обработчики для клиентской части (запись на услуги)
"""
from datetime import datetime, timedelta, date, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import async_session_maker
from database.models import Employee, Booking, Business
from database.crud import (
    get_or_create_user,
    get_all_active_businesses,
    get_business_services,
    get_business_main_services,
    get_business_additional_services,
    get_business_employees,
    create_booking,
    get_user_bookings,
    update_booking_status,
    get_business_by_id,
    get_service_by_id,
    get_user_businesses,
    get_employee_by_telegram_id,
    get_employee_days_off,
    is_employee_day_off,
    get_employees_for_services,
    get_employee_service_ids,
    get_client_subscription_by_id,
    use_subscription_service,
    check_subscription_service_available,
)
from bot.states import BookingStates
from bot.keyboards import client_kb
from bot.config import ADMIN_IDS
from bot.utils.validators import format_date_with_weekday, format_phone
from bot.services.mlm_sync import can_be_business_owner

router = Router()

# Русские названия дней недели (сокращённые)
WEEKDAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


def generate_available_dates(days_ahead: int = 30, exclude_dates: list = None):
    """Генерация списка дат на месяц вперёд

    Args:
        days_ahead: количество дней вперёд
        exclude_dates: список дат (date), которые нужно исключить (выходные мастера)
    """
    from datetime import datetime, timedelta
    available_dates = []
    today = datetime.now().date()
    exclude_dates = exclude_dates or []

    for i in range(days_ahead):
        future_date = today + timedelta(days=i)

        # Пропускаем выходные дни мастера
        if future_date in exclude_dates:
            continue

        day_num = future_date.day
        weekday = WEEKDAY_NAMES[future_date.weekday()]

        available_dates.append({
            'display': f"{day_num} {weekday}",
            'value': future_date.strftime("%d.%m.%Y")
        })

    return available_dates


async def get_employee_days_off_dates(employee_id: int, days_ahead: int = 30) -> list:
    """Получить список дат выходных сотрудника"""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    end_date = today + timedelta(days=days_ahead)

    async with async_session_maker() as session:
        days_off = await get_employee_days_off(session, employee_id, today, end_date)
        return [d.date for d in days_off]


async def calculate_venue_time_slots(business_id: int, employee_id: int, selected_date, total_duration: int):
    """Рассчитать доступные и занятые слоты времени для помещения на дату

    Args:
        business_id: ID бизнеса
        employee_id: ID помещения (employee)
        selected_date: дата (date объект)
        total_duration: общая длительность выбранных услуг в минутах

    Returns:
        tuple: (available_times, occupied_times) - списки строк HH:MM
    """
    from sqlalchemy import and_, or_

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

        # Определяем шаг записи
        interval = business.booking_interval_minutes
        result = await session.execute(
            select(Employee).where(Employee.id == employee_id)
        )
        employee = result.scalar_one_or_none()
        if employee and employee.booking_interval_minutes:
            interval = employee.booking_interval_minutes

        # Проверка мин. времени бронирования
        if employee and employee.min_booking_minutes and total_duration < employee.min_booking_minutes:
            return [], []  # Не показываем слоты если длительность меньше минимума

        # Время работы
        start_time = business.working_hours_start or datetime.strptime("09:00", "%H:%M").time()
        end_time = business.working_hours_end or datetime.strptime("18:00", "%H:%M").time()

        # Cross-midnight: если end < start, конец рабочего дня — на следующий день
        is_cross_midnight = end_time < start_time

        # Для cross-midnight запрашиваем бронирования за 2 дня (selected + prev_day)
        prev_day = selected_date - timedelta(days=1)
        next_day = selected_date + timedelta(days=1)
        if is_cross_midnight:
            date_filter = Booking.booking_date.in_([selected_date, prev_day])
        else:
            date_filter = Booking.booking_date == selected_date

        # Существующие записи для этого помещения
        result = await session.execute(
            select(Booking)
            .options(selectinload(Booking.service))
            .where(
                and_(
                    Booking.business_id == business_id,
                    Booking.employee_id == employee_id,
                    date_filter,
                    Booking.status.in_(["pending", "confirmed"])
                )
            )
        )
        existing_bookings = result.scalars().all()

    service_duration = total_duration
    available_times = []
    occupied_times = []
    current_time = datetime.combine(selected_date, start_time)

    if is_cross_midnight:
        end_datetime = datetime.combine(next_day, end_time)
    else:
        end_datetime = datetime.combine(selected_date, end_time)

    # Если сегодня, начинаем с текущего времени + 1 час
    if selected_date == datetime.now().date():
        now_plus_hour = datetime.now() + timedelta(hours=1)
        if current_time < now_plus_hour:
            current_time = now_plus_hour
            minutes = (current_time.minute // interval + 1) * interval
            if minutes >= 60:
                current_time = current_time.replace(minute=0) + timedelta(hours=1)
            else:
                current_time = current_time.replace(minute=minutes)

    # Конвертируем существующие бронирования в абсолютные datetime
    booking_ranges = []
    for booking in existing_bookings:
        b_start = datetime.combine(booking.booking_date, booking.booking_time)
        b_dur = booking.service.duration_minutes if booking.service else 60
        b_end = b_start + timedelta(minutes=b_dur)
        # Если бронирование с предыдущего дня пересекает полночь
        if is_cross_midnight and booking.booking_date == prev_day and b_end.date() >= selected_date:
            booking_ranges.append((b_start, b_end))
        elif booking.booking_date == selected_date:
            booking_ranges.append((b_start, b_end))

    while current_time + timedelta(minutes=service_duration) <= end_datetime:
        is_break = False
        if business.break_start and business.break_end:
            ct = current_time.time()
            if business.break_start <= ct < business.break_end:
                is_break = True

        slot_occupied = False
        if not is_break:
            slot_end_time = current_time + timedelta(minutes=service_duration)

            for b_start, b_end in booking_ranges:
                # Проверяем пересечение полной длительности услуги с бронированием
                if not (slot_end_time <= b_start or current_time >= b_end):
                    slot_occupied = True
                    break

        if not is_break:
            if slot_occupied:
                occupied_times.append(current_time.strftime("%H:%M"))
            else:
                available_times.append(current_time.strftime("%H:%M"))

        current_time += timedelta(minutes=interval)

    return available_times, occupied_times


async def get_user_roles(telegram_id: int):
    """Проверка ролей пользователя для кнопок переключения режимов"""
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=telegram_id,
            username=None,
            full_name=""
        )
        businesses = await get_user_businesses(session, user.id)
        employee = await get_employee_by_telegram_id(session, telegram_id)

    is_admin = telegram_id in ADMIN_IDS
    mlm_owner = await can_be_business_owner(telegram_id)
    show_admin = is_admin or len(businesses) > 0 or mlm_owner
    show_master = employee is not None

    return show_admin, show_master


# ===== НАЧАЛО ПРОЦЕССА ЗАПИСИ =====

@router.message(F.text == "📅 Записаться")
async def start_booking(message: Message, state: FSMContext):
    """Начало процесса записи"""
    async with async_session_maker() as session:
        businesses = await get_all_active_businesses(session)

    if not businesses:
        await message.answer(
            "😔 К сожалению, сейчас нет доступных заведений для записи.\n\n"
            "Попробуйте позже! 🙏"
        )
        return

    # Получаем роли пользователя для кнопок переключения
    show_admin, show_master = await get_user_roles(message.from_user.id)

    # Показываем Reply клавиатуру с основным меню клиента
    reply_keyboard = client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)

    # Отправляем reply клавиатуру и inline для выбора бизнеса
    await message.answer(
        "📍 Меню внизу ⬇️",
        reply_markup=reply_keyboard
    )
    await message.answer(
        "🏢 Выберите заведение:",
        reply_markup=client_kb.get_businesses_keyboard(businesses)
    )

    await state.set_state(BookingStates.choosing_business)


# ===== ВЫБОР БИЗНЕСА =====

@router.callback_query(F.data.startswith("biz_page:"), BookingStates.choosing_business)
async def businesses_pagination(callback: CallbackQuery, state: FSMContext):
    """Пагинация списка бизнесов"""
    page = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        businesses = await get_all_active_businesses(session)

    await callback.message.edit_text(
        "🏢 Выберите заведение:",
        reply_markup=client_kb.get_businesses_keyboard(businesses, page=page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("business:"), BookingStates.choosing_business)
async def business_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора бизнеса"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        services = await get_business_services(session, business_id)

    if not services:
        await callback.message.answer(
            f"В бизнесе '{business.name}' пока нет доступных услуг."
        )
        await callback.answer()
        return

    # Сохраняем выбранный бизнес
    await state.update_data(business_id=business_id, business_name=business.name, business_type=business.business_type)

    # Формируем информацию о бизнесе
    import json
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from urllib.parse import quote

    info_text = f"🏢 <b>{business.name}</b>\n\n"

    if business.description:
        info_text += f"📝 {business.description}\n\n"

    # Контакты
    if business.phone:
        formatted_phone = format_phone(business.phone)
        info_text += f'📞 Телефон: {formatted_phone}\n'

    if business.address:
        encoded_address = quote(business.address)
        yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
        info_text += f'📍 Адрес: <a href="{yandex_maps_url}">{business.address}</a>\n'

    # Часы работы
    if business.working_hours_start and business.working_hours_end:
        info_text += f"⏰ Часы работы: {business.working_hours_start.strftime('%H:%M')} - {business.working_hours_end.strftime('%H:%M')}\n"

    # Время перерыва
    if business.break_start and business.break_end:
        info_text += f"☕ Перерыв: {business.break_start.strftime('%H:%M')} - {business.break_end.strftime('%H:%M')}\n"

    info_text += "\n"

    # Проверяем наличие фото и инструкций
    has_photos = False
    has_directions = False

    if business.photos:
        try:
            photos_data = json.loads(business.photos)
            has_photos = len(photos_data) > 0
        except:
            pass

    has_directions = business.directions is not None and business.directions.strip() != ""

    # Создаем клавиатуру
    builder = InlineKeyboardBuilder()

    if has_photos:
        builder.button(text="📷 Фото заведения", callback_data=f"booking_view_photos:{business_id}")
    if getattr(business, 'video', None):
        builder.button(text="🎬 Видеообзор", callback_data=f"business_video:{business_id}")
    if has_directions:
        builder.button(text="🗺 Как добраться", callback_data=f"booking_view_directions:{business_id}")

    # Кнопка "Посмотреть залы" для аренды помещений
    from bot.utils.business_types import is_venue_rental_type as _biz_venue_check
    if _biz_venue_check(business.business_type):
        builder.button(text="👀 Посмотреть залы", callback_data=f"view_rooms:{business_id}")

    builder.button(text="➡️ Продолжить запись", callback_data=f"continue_booking:{business_id}", style="primary")
    builder.button(text="◀️ Назад к выбору", callback_data="back_to_businesses")
    builder.adjust(1)

    await callback.message.edit_text(
        info_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=builder.as_markup()
    )
    await state.set_state(BookingStates.choosing_business)
    await callback.answer()


# ===== ПРОСМОТР ЗАЛОВ =====

@router.callback_query(F.data.startswith("view_rooms:"), BookingStates.choosing_business)
async def view_rooms_list(callback: CallbackQuery, state: FSMContext):
    """Список залов бизнеса для просмотра"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        employees = await get_business_employees(session, business_id)
        employees = [e for e in employees if e.is_active and e.role in ("master", "master_and_admin")]

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for emp in employees:
        builder.button(text=f"🏠 {emp.name}", callback_data=f"view_room:{emp.id}")
    builder.button(text="◀️ Назад", callback_data=f"business:{business_id}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🏢 <b>{business.name}</b>\n\n"
        f"👀 Выберите зал для просмотра:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_room:"), BookingStates.choosing_business)
async def view_room_detail(callback: CallbackQuery, state: FSMContext):
    """Показать детали зала: описание, фото, видео"""
    employee_id = int(callback.data.split(":")[1])
    import json as _rjson
    from database.crud import get_employee_by_id
    async with async_session_maker() as session:
        employee = await get_employee_by_id(session, employee_id)
        business = await get_business_by_id(session, employee.business_id)

    # Формируем текст
    text = f"🏠 <b>{employee.name}</b>\n\n"
    if employee.capacity:
        text += f"👥 Вместимость: {employee.capacity} чел.\n"
    if employee.area_sqm:
        text += f"📐 Площадь: {employee.area_sqm} м²\n"
    if employee.description:
        text += f"\n📝 {employee.description}\n"

    # Отправляем фото
    photos = []
    if employee.photos:
        try:
            photos = _rjson.loads(employee.photos)
        except Exception:
            pass

    if photos:
        from aiogram.types import InputMediaPhoto
        media = [InputMediaPhoto(media=fid) for fid in photos[:10]]
        media[0].caption = text
        media[0].parse_mode = "HTML"
        await callback.message.answer_media_group(media)
    else:
        await callback.message.answer(text, parse_mode="HTML")

    # Отправляем видео
    if employee.video:
        if employee.video.startswith("video_note:"):
            fid = employee.video[len("video_note:"):]
            await callback.message.answer_video_note(fid)
        else:
            await callback.message.answer_video(employee.video)

    # Если нет ни фото ни видео ни описания
    if not photos and not employee.video and not employee.description:
        await callback.message.answer(
            f"🏠 <b>{employee.name}</b>\n\nИнформация пока не добавлена.",
            parse_mode="HTML"
        )

    # Кнопка назад
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ К списку залов", callback_data=f"view_rooms:{employee.business_id}")
    builder.button(text="➡️ Продолжить запись", callback_data=f"continue_booking:{employee.business_id}", style="primary")
    builder.adjust(1)

    await callback.message.answer(
        "Выберите действие:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ===== ПРОДОЛЖЕНИЕ ЗАПИСИ ПОСЛЕ ПРОСМОТРА ИНФОРМАЦИИ =====

@router.callback_query(F.data.startswith("continue_booking:"), BookingStates.choosing_business)
async def continue_booking_after_info(callback: CallbackQuery, state: FSMContext):
    """Продолжение записи после просмотра информации о бизнесе"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        from bot.utils.business_types import is_venue_rental_type as _is_venue
        is_venue = _is_venue(business.business_type)
        if is_venue:
            services = await get_business_main_services(session, business_id)
        else:
            services = await get_business_services(session, business_id)

        # Проверяем наличие тарифов по времени (для venue_rental)
        has_time_pricing = False
        if is_venue:
            from database.crud import get_employee_time_pricing
            employees = await get_business_employees(session, business_id)
            for emp in employees:
                rules = await get_employee_time_pricing(session, emp.id)
                if rules:
                    has_time_pricing = True
                    break

        # Проверяем наличие активных абонементов у клиента
        from database.crud import get_client_available_services, get_business_subscriptions
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )
        available_sub_services = await get_client_available_services(session, user.id, business_id)
        business_subscriptions = await get_business_subscriptions(session, business_id, active_only=True)

    # Инициализируем пустой список выбранных услуг
    await state.update_data(selected_service_ids=[], use_subscription=False)

    # Формируем текст с описаниями услуг
    services_text = f"🏢 <b>{business.name}</b>\n\n📋 <b>Выберите услуги:</b>\n\n"
    if has_time_pricing:
        services_text += "💰 <i>Цена зависит от выбранного времени</i>\n\n"
    for service in services:
        if has_time_pricing:
            price_text = ""
        else:
            price_text = f" • {service.price}₽" if service.price else ""
        duration_text = f"{service.duration_minutes} мин" if service.duration_minutes and service.duration_minutes > 0 else ""
        if duration_text and price_text:
            info_text = f"({duration_text}{price_text})"
        elif duration_text:
            info_text = f"({duration_text})"
        elif price_text:
            info_text = f"({service.price}₽)"
        else:
            info_text = ""
        services_text += f"▪️ <b>{service.name}</b> {info_text}\n"
        if service.description:
            services_text += f"   <i>{service.description}</i>\n"
    services_text += "\n<i>Нажмите на услугу для выбора</i>"

    # Создаем клавиатуру с учетом абонементов
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    # Если есть активные абонементы с доступными услугами - показываем кнопку
    if available_sub_services:
        builder.button(
            text=f"🎫 Использовать абонемент ({len(available_sub_services)} услуг)",
            callback_data=f"use_subscription:{business_id}"
        )

    # Добавляем услуги
    for service in services:
        if has_time_pricing:
            price_text = ""
        else:
            price_text = f" - {service.price}₽" if service.price else ""
        duration_text = f"{service.duration_minutes} мин" if service.duration_minutes and service.duration_minutes > 0 else ""
        if duration_text and price_text:
            info_text = f" ({duration_text}{price_text})"
        elif duration_text:
            info_text = f" ({duration_text})"
        elif price_text:
            info_text = f" ({service.price}₽)"
        else:
            info_text = ""
        builder.button(
            text=f"{service.name}{info_text}",
            callback_data=f"service:{service.id}"
        )

    # Если есть абонементы для покупки - показываем кнопку
    if business_subscriptions:
        builder.button(text="🎫 Купить абонемент", callback_data=f"view_subscriptions:{business_id}")

    builder.button(text="◀️ Назад", callback_data="back_to_businesses")
    builder.button(text="🏠 Главное меню", callback_data="client_main_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        services_text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


# ===== ИСПОЛЬЗОВАНИЕ АБОНЕМЕНТА ПРИ ЗАПИСИ =====

@router.callback_query(F.data.startswith("use_sub_svc:"))
async def use_subscription_service_for_booking(callback: CallbackQuery, state: FSMContext):
    """Выбор услуги из абонемента для бронирования"""
    parts = callback.data.split(":")
    client_sub_id = int(parts[1])
    service_id = int(parts[2])

    async with async_session_maker() as session:
        # Проверяем доступность услуги
        is_available = await check_subscription_service_available(session, client_sub_id, service_id)
        if not is_available:
            await callback.answer("Эта услуга уже израсходована в абонементе", show_alert=True)
            return

        # Получаем информацию об абонементе и услуге
        client_sub = await get_client_subscription_by_id(session, client_sub_id)
        service = await get_service_by_id(session, service_id)
        business = await get_business_by_id(session, client_sub.business_id)

    # Сохраняем информацию об использовании абонемента
    await state.update_data(
        use_subscription=True,
        client_subscription_id=client_sub_id,
        business_id=client_sub.business_id,
        business_name=business.name,
        selected_service_ids=[service_id],
        services_info=[{
            'id': service.id,
            'name': service.name,
            'duration': service.duration_minutes,
            'price': 0  # Бесплатно по абонементу
        }],
        total_duration=service.duration_minutes,
        total_price=0,
        subscription_name=client_sub.subscription.name
    )

    # Переходим к выбору мастера
    employees = await get_employees_for_services(
        session if 'session' in dir() else async_session_maker(),
        [service_id],
        client_sub.business_id
    )

    async with async_session_maker() as session:
        employees = await get_employees_for_services(session, [service_id], client_sub.business_id)

    from bot.utils.business_types import get_terminology, is_venue_rental_type
    term = get_terminology(business.business_type)

    if not employees:
        await callback.message.edit_text(
            f"К сожалению, нет доступных {term.get('employee_plural', 'мастеров')} "
            f"для услуги '{service.name}'.",
            reply_markup=client_kb.get_back_to_services_keyboard()
        )
        await callback.answer()
        return

    text = (
        f"🎫 <b>Запись по абонементу</b>\n\n"
        f"📋 Услуга: {service.name}\n"
        f"🎫 Абонемент: {client_sub.subscription.name}\n\n"
        f"Выберите {term.get('employee_singular', 'мастера')}:"
    )

    if is_venue_rental_type(business.business_type):
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=client_kb.get_employees_venue_keyboard(employees, business.business_type)
        )
    else:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=client_kb.get_employees_keyboard(employees)
        )

    await state.set_state(BookingStates.choosing_employee)
    await callback.answer()


@router.callback_query(F.data.startswith("booking_view_photos:"), BookingStates.choosing_business)
async def booking_view_photos_handler(callback: CallbackQuery, state: FSMContext):
    """Просмотр фото во время записи"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business or not business.photos:
        await callback.answer("Фотографии не найдены", show_alert=True)
        return

    import json
    from aiogram.types import InputMediaPhoto
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    try:
        photos_data = json.loads(business.photos)
        if not photos_data:
            await callback.answer("Фотографии не найдены", show_alert=True)
            return

        # Отправляем фотографии
        media_group = []
        for i, photo_id in enumerate(photos_data[:10]):
            if i == 0:
                media_group.append(InputMediaPhoto(
                    media=photo_id,
                    caption=f"📷 {business.name}"
                ))
            else:
                media_group.append(InputMediaPhoto(media=photo_id))

        await callback.message.answer_media_group(media_group)

        # Кнопки навигации
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад к информации", callback_data=f"business:{business_id}")
        builder.adjust(1)

        await callback.message.answer("Вернуться:", reply_markup=builder.as_markup())
        await callback.answer()

    except Exception as e:
        await callback.answer("Ошибка при загрузке фотографий", show_alert=True)


@router.callback_query(F.data.startswith("business_video:"), BookingStates.choosing_business)
async def business_video_handler(callback: CallbackQuery, state: FSMContext):
    """Просмотр видеообзора бизнеса"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business or not getattr(business, 'video', None):
        await callback.answer("Видео не найдено", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    try:
        await callback.message.answer_video(
            business.video,
            caption=f"🎬 {business.name}"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад к информации", callback_data=f"business:{business_id}")
        builder.adjust(1)

        await callback.message.answer("Вернуться:", reply_markup=builder.as_markup())
        await callback.answer()

    except Exception:
        await callback.answer("Ошибка при загрузке видео", show_alert=True)


@router.callback_query(F.data.startswith("booking_view_directions:"), BookingStates.choosing_business)
async def booking_view_directions_handler(callback: CallbackQuery, state: FSMContext):
    """Просмотр инструкций во время записи"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business or not business.directions:
        await callback.answer("Инструкция не найдена", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from urllib.parse import quote

    # Формируем текст с адресом
    address_text = ""
    if business.address:
        encoded_address = quote(business.address)
        yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
        gis_url = f"https://2gis.ru/search/{encoded_address}"
        address_text = f'\n\n📍 <b>Адрес:</b> <a href="{yandex_maps_url}">{business.address}</a>\n\n' \
                      f'🗺 <a href="{yandex_maps_url}">Яндекс.Карты</a> | ' \
                      f'<a href="{gis_url}">2ГИС</a>'

    directions_text = f"🗺 <b>Как добраться</b>\n\n{business.directions}{address_text}"

    # Кнопки навигации
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад к информации", callback_data=f"business:{business_id}")
    builder.adjust(1)

    await callback.message.answer(
        directions_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ===== ВЫБОР УСЛУГИ =====

@router.callback_query(F.data.startswith("service:"), BookingStates.choosing_service)
async def service_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора услуги (множественный выбор)"""
    service_id = int(callback.data.split(":")[1])

    data = await state.get_data()
    business_id = data["business_id"]
    selected_service_ids = data.get("selected_service_ids", [])

    # Проверяем, является ли услуга контактной (tariff_description)
    async with async_session_maker() as _svc_session:
        _clicked_svc = await get_service_by_id(_svc_session, service_id)
        _is_contact = hasattr(_clicked_svc, 'tariff_description') and _clicked_svc.tariff_description if _clicked_svc else False

    # Переключаем выбор услуги (добавляем или удаляем)
    if service_id in selected_service_ids:
        selected_service_ids.remove(service_id)
    else:
        if _is_contact:
            # Контактная услуга — эксклюзивный выбор
            selected_service_ids = [service_id]
        else:
            # Обычная услуга — убираем контактные из выбора
            async with async_session_maker() as _flt_session:
                new_ids = []
                for sid in selected_service_ids:
                    s = await get_service_by_id(_flt_session, sid)
                    if not (hasattr(s, 'tariff_description') and s.tariff_description):
                        new_ids.append(sid)
                selected_service_ids = new_ids
            selected_service_ids.append(service_id)

    await state.update_data(selected_service_ids=selected_service_ids)

    # Обновляем клавиатуру с новым состоянием выбора
    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        from bot.utils.business_types import is_venue_rental_type as _is_venue2
        if _is_venue2(business.business_type):
            services = await get_business_main_services(session, business_id)
        else:
            services = await get_business_services(session, business_id)

    # Формируем текст с описаниями услуг
    services_text = f"🏢 <b>{business.name}</b>\n\n📋 <b>Выберите услуги:</b>\n\n"
    for service in services:
        price_text = f" • {service.price}₽" if service.price else ""
        duration_text = f"{service.duration_minutes} мин" if service.duration_minutes and service.duration_minutes > 0 else ""
        if duration_text and price_text:
            info_text = f"({duration_text}{price_text})"
        elif duration_text:
            info_text = f"({duration_text})"
        elif price_text:
            info_text = f"({service.price}₽)"
        else:
            info_text = ""
        services_text += f"▪️ <b>{service.name}</b> {info_text}\n"
        if service.description:
            services_text += f"   <i>{service.description}</i>\n"
    services_text += "\n<i>Нажмите на услугу для выбора</i>"

    await callback.message.edit_text(
        services_text,
        parse_mode="HTML",
        reply_markup=client_kb.get_services_keyboard(services, selected_ids=selected_service_ids)
    )
    await callback.answer()


@router.callback_query(F.data == "services_done", BookingStates.choosing_service)
async def services_selection_done(callback: CallbackQuery, state: FSMContext):
    """Завершение выбора услуг и переход к выбору мастера"""
    data = await state.get_data()
    selected_service_ids = data.get("selected_service_ids", [])
    business_id = data["business_id"]

    if not selected_service_ids:
        await callback.answer("Выберите хотя бы одну услугу", show_alert=True)
        return

    # Получаем информацию о выбранных услугах
    async with async_session_maker() as session:
        # Получаем бизнес для определения типа
        business = await get_business_by_id(session, business_id)

        services = []
        total_duration = 0
        total_price = 0
        for service_id in selected_service_ids:
            service = await get_service_by_id(session, service_id)
            services.append(service)
            total_duration += service.duration_minutes
            if service.price:
                total_price += service.price

        # Проверяем, есть ли "контактная" услуга (с tariff_description)
        contact_service = None
        for svc in services:
            if hasattr(svc, 'tariff_description') and svc.tariff_description:
                contact_service = svc
                break

        if contact_service:
            # Показываем тарифы и кнопку связи с владельцем
            owner = business.owner if business.owner else None
            owner_username = owner.username if owner else None

            text = f"📋 <b>{contact_service.name}</b>\n\n"
            text += contact_service.tariff_description

            buttons = []
            if owner_username:
                buttons.append([InlineKeyboardButton(
                    text="💬 Связаться с владельцем",
                    url=f"https://t.me/{owner_username}"
                )])
            buttons.append([InlineKeyboardButton(
                text="⬅️ Назад к услугам",
                callback_data="back_to_services"
            )])

            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Получаем мастеров, которые могут делать ВСЕ выбранные услуги
        # Если у мастера не назначены услуги - он может делать все (обратная совместимость)
        all_employees = await get_business_employees(session, business_id)
        all_employees = [e for e in all_employees if e.role in ("master", "master_and_admin")]

        # Фильтруем мастеров по услугам
        employees = []
        for emp in all_employees:
            emp_service_ids = await get_employee_service_ids(session, emp.id)
            if not emp_service_ids:
                # Если у мастера нет назначенных услуг - он может делать всё
                employees.append(emp)
            elif all(sid in emp_service_ids for sid in selected_service_ids):
                # Мастер может делать все выбранные услуги
                employees.append(emp)

        # Если нет мастеров для ВСЕХ услуг, проверяем пошаговый выбор
        services_masters_mapping = {}
        if not employees and len(selected_service_ids) > 1:
            # Для каждой услуги находим мастеров, которые её могут делать
            for service in services:
                available_for_service = []
                for emp in all_employees:
                    emp_service_ids = await get_employee_service_ids(session, emp.id)
                    if not emp_service_ids:
                        # Мастер без назначенных услуг может делать всё
                        available_for_service.append(emp)
                    elif service.id in emp_service_ids:
                        available_for_service.append(emp)
                services_masters_mapping[service.id] = {
                    "service": service,
                    "employees": available_for_service
                }

    # Проверяем наличие тарифов по времени (для venue_rental)
    from bot.utils.business_types import is_venue_rental_type as _is_venue_check
    has_time_pricing = False
    if _is_venue_check(business.business_type):
        async with async_session_maker() as session:
            from database.crud import get_employee_time_pricing
            for emp in all_employees:
                rules = await get_employee_time_pricing(session, emp.id)
                if rules:
                    has_time_pricing = True
                    break

    # Сохраняем информацию о выбранных услугах и типе бизнеса
    # Цены НЕ обнуляем — они используются как фолбэк если время не попадает в тарифную зону
    services_info = []
    for service in services:
        services_info.append({
            "id": service.id,
            "name": service.name,
            "duration": service.duration_minutes,
            "price": service.price
        })

    await state.update_data(
        services_info=services_info,
        total_duration=total_duration,
        total_price=total_price,
        has_time_pricing=has_time_pricing,
        business_type=business.business_type
    )

    # Определяем терминологию
    from bot.utils.business_types import is_venue_rental_type
    is_venue = is_venue_rental_type(business.business_type)
    employee_label = "🏠 Выберите помещение:" if is_venue else "👤 Выберите специалиста:"
    selected_label = "✅ Выбранное время:" if is_venue else "✅ Выбранные услуги:"

    # Формируем текст с выбранными услугами (без времени для услуг с duration=0)
    def format_service(s):
        if s.duration_minutes and s.duration_minutes > 0:
            return f"• {s.name} ({s.duration_minutes} мин)"
        return f"• {s.name}"
    services_text = "\n".join([format_service(s) for s in services])
    price_text = f"\n💰 Общая стоимость: {total_price}₽" if total_price > 0 else ""

    if employees:
        # Есть мастера/помещения, которые могут выполнить ВСЕ услуги
        if len(employees) == 1:
            # Только один мастер/помещение - автоматически выбираем и переходим к дате
            single_employee = employees[0]
            await state.update_data(employee_id=single_employee.id)

            # Показываем календарь вместо выбора мастера
            year = datetime.now().year
            month = datetime.now().month

            # Получаем выходные мастера
            exclude_dates = await get_employee_days_off(session, single_employee.id)
            exclude_dates = [d.date for d in exclude_dates]

            await callback.message.edit_text(
                f"{selected_label}\n{services_text}\n"
                f"⏱ Общая длительность: {total_duration} мин{price_text}\n"
                f"👤 {single_employee.name}\n\n"
                f"📅 Выберите дату:",
                reply_markup=client_kb.get_booking_calendar_keyboard(
                    year, month,
                    exclude_dates=exclude_dates,
                    callback_prefix="date",
                    back_callback="back_to_services"
                )
            )
            await state.set_state(BookingStates.choosing_date)
            await callback.answer()
            return

        # Для аренды помещений: пропускаем выбор помещения, сразу показываем календарь
        # Помещение будет выбрано на экране выбора времени
        if is_venue:
            # Фильтруем комнаты по available_employee_ids услуг
            import json as _json_mod
            filtered_employees = employees
            for service in services:
                if service.available_employee_ids:
                    try:
                        allowed_ids = _json_mod.loads(service.available_employee_ids)
                        filtered_employees = [e for e in filtered_employees if e.id in allowed_ids]
                    except Exception:
                        pass
            if not filtered_employees:
                filtered_employees = employees  # Fallback
            venue_room_ids = [e.id for e in filtered_employees]
            await state.update_data(venue_room_ids=venue_room_ids)

            year = datetime.now().year
            month = datetime.now().month

            await callback.message.edit_text(
                f"{selected_label}\n{services_text}\n"
                f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
                f"📅 Выберите дату:",
                reply_markup=client_kb.get_booking_calendar_keyboard(
                    year, month,
                    exclude_dates=[],
                    callback_prefix="date",
                    back_callback="back_to_services"
                )
            )
            await state.set_state(BookingStates.choosing_date)
            await callback.answer()
            return

        # Несколько мастеров (не аренда) - показываем выбор
        await callback.message.edit_text(
            f"{selected_label}\n{services_text}\n"
            f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
            f"{employee_label}",
            reply_markup=client_kb.get_employees_venue_keyboard(employees, business.business_type)
        )
        await state.set_state(BookingStates.choosing_employee)
        await callback.answer()
        return

    # Нет мастеров для ВСЕХ услуг - проверяем пошаговый выбор
    if services_masters_mapping:
        # Проверяем, что для каждой услуги есть хотя бы один мастер
        all_have_masters = all(
            len(svc_mapping["employees"]) > 0
            for svc_mapping in services_masters_mapping.values()
        )

        if all_have_masters:
            # Запускаем пошаговый выбор мастеров
            # Сохраняем mapping и индекс текущей услуги
            services_for_selection = []
            selected_employees = {}  # Авто-назначаем единственных мастеров
            for service_id in selected_service_ids:
                svc_data = services_masters_mapping[service_id]
                emp_list = svc_data["employees"]
                services_for_selection.append({
                    "service_id": service_id,
                    "service_name": svc_data["service"].name,
                    "employee_ids": [e.id for e in emp_list]
                })
                # Авто-назначаем если только один мастер доступен
                if len(emp_list) == 1:
                    selected_employees[str(service_id)] = emp_list[0].id

            # Ищем первую услугу, которая требует ручного выбора
            first_manual_index = None
            for i, svc_sel in enumerate(services_for_selection):
                if str(svc_sel["service_id"]) not in selected_employees:
                    first_manual_index = i
                    break

            # Определяем терминологию для пошагового выбора
            from bot.utils.business_types import get_terminology
            term = get_terminology(business.business_type)
            emp_singular = term.get("employee", "Мастер")
            emp_lower = term.get("employee_acc", "мастера")

            if first_manual_index is None:
                # Все мастера авто-назначены — сразу к выбору даты
                await state.update_data(
                    per_service_selection=True,
                    services_for_selection=services_for_selection,
                    selected_employees_per_service=selected_employees,
                    employee_id=list(selected_employees.values())[0],
                    employee_name="Разные мастера" if len(set(selected_employees.values())) > 1 else None,
                    per_service_employees=selected_employees
                )

                # Получаем имя мастера если один для всех
                if len(set(selected_employees.values())) == 1:
                    async with async_session_maker() as session:
                        result = await session.execute(
                            select(Employee).where(Employee.id == list(selected_employees.values())[0])
                        )
                        single_emp = result.scalar_one_or_none()
                        if single_emp:
                            await state.update_data(employee_name=single_emp.name)

                # Формируем текст с выбранными мастерами
                async with async_session_maker() as session:
                    selections_text = []
                    for svc_info in data.get("services_info", []):
                        emp_id = selected_employees.get(str(svc_info["id"]))
                        if emp_id:
                            result = await session.execute(
                                select(Employee).where(Employee.id == emp_id)
                            )
                            emp = result.scalar_one_or_none()
                            emp_name = emp.name if emp else "Мастер"
                            selections_text.append(f"• {svc_info['name']} — {emp_name}")

                # Получаем выходные дни
                all_exclude_dates = set()
                async with async_session_maker() as session:
                    for emp_id in selected_employees.values():
                        exclude_dates = await get_employee_days_off_dates(emp_id, 60)
                        all_exclude_dates.update(exclude_dates)

                today = date.today()
                await callback.message.edit_text(
                    f"✅ Выбранные услуги и мастера:\n" + "\n".join(selections_text) + f"\n"
                    f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
                    f"📅 Выберите дату:\n"
                    f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
                    parse_mode="HTML",
                    reply_markup=client_kb.get_booking_calendar_keyboard(
                        today.year, today.month,
                        exclude_dates=list(all_exclude_dates),
                        callback_prefix="date",
                        back_callback="back_to_per_service_selection"
                    )
                )
                await state.set_state(BookingStates.choosing_date)
                await callback.answer()
                return

            await state.update_data(
                per_service_selection=True,
                services_for_selection=services_for_selection,
                current_service_index=first_manual_index,
                selected_employees_per_service=selected_employees
            )

            # Показываем выбор мастера для первой услуги, требующей выбора
            first_svc_data = services_masters_mapping[services_for_selection[first_manual_index]["service_id"]]
            first_service = first_svc_data["service"]
            first_employees = first_svc_data["employees"]

            # Формируем текст с уже авто-назначенными мастерами
            auto_assigned_text = ""
            if selected_employees:
                auto_parts = []
                async with async_session_maker() as session:
                    for svc_sel in services_for_selection:
                        sid = str(svc_sel["service_id"])
                        if sid in selected_employees:
                            result = await session.execute(
                                select(Employee).where(Employee.id == selected_employees[sid])
                            )
                            emp = result.scalar_one_or_none()
                            emp_name = emp.name if emp else "?"
                            auto_parts.append(f"✅ {svc_sel['service_name']} — {emp_name}")
                        else:
                            auto_parts.append(f"◻️ {svc_sel['service_name']}")
                auto_assigned_text = f"📋 Выбор мастеров:\n" + "\n".join(auto_parts) + "\n\n"

            await callback.message.edit_text(
                f"{auto_assigned_text}"
                f"👤 Выберите {emp_lower} для услуги:\n<b>{first_service.name}</b>",
                parse_mode="HTML",
                reply_markup=client_kb.get_employees_for_service_keyboard(
                    first_employees, first_service.id, first_service.name, business.business_type
                )
            )
            await state.set_state(BookingStates.choosing_employee_per_service)
            await callback.answer()
            return

    # Нет мастеров/помещений вообще
    from bot.utils.business_types import get_terminology
    term = get_terminology(business.business_type)
    emp_plural = term.get("employee_plural", "мастеров")

    await callback.message.edit_text(
        f"✅ Выбранные услуги:\n{services_text}\n"
        f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
        f"😔 К сожалению, сейчас нет {emp_plural} для выбранных услуг.\n\n"
        "Попробуйте выбрать другую комбинацию услуг 🙏",
        reply_markup=client_kb.get_back_to_services_keyboard()
    )
    await callback.answer()


# ===== ПОШАГОВЫЙ ВЫБОР МАСТЕРА ДЛЯ КАЖДОЙ УСЛУГИ =====

@router.callback_query(F.data.startswith("emp_for_svc:"), BookingStates.choosing_employee_per_service)
async def employee_for_service_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора мастера для конкретной услуги (пошаговый выбор)"""
    parts = callback.data.split(":")
    service_id = int(parts[1])
    employee_id = int(parts[2])

    data = await state.get_data()
    services_for_selection = data.get("services_for_selection", [])
    current_index = data.get("current_service_index", 0)
    selected_employees = data.get("selected_employees_per_service", {})

    # Сохраняем выбор мастера для текущей услуги
    selected_employees[str(service_id)] = employee_id
    await state.update_data(selected_employees_per_service=selected_employees)

    # Получаем имя выбранного мастера для отображения
    async with async_session_maker() as session:
        result = await session.execute(
            select(Employee).where(Employee.id == employee_id)
        )
        selected_employee = result.scalar_one_or_none()
        selected_emp_name = selected_employee.name if selected_employee else "Мастер"

    # Переходим к следующей услуге
    next_index = current_index + 1

    if next_index >= len(services_for_selection):
        # Все мастера выбраны, переходим к выбору даты
        # Формируем текст с выбранными услугами и мастерами
        services_info = data.get("services_info", [])
        total_duration = data.get("total_duration", 0)
        total_price = data.get("total_price", 0)

        # Получаем имена всех мастеров
        async with async_session_maker() as session:
            selections_text = []
            for svc_info in services_info:
                emp_id = selected_employees.get(str(svc_info["id"]))
                if emp_id:
                    result = await session.execute(
                        select(Employee).where(Employee.id == emp_id)
                    )
                    emp = result.scalar_one_or_none()
                    emp_name = emp.name if emp else "Мастер"
                    selections_text.append(f"• {svc_info['name']} — {emp_name}")

        # Сохраняем информацию о выборе
        # Для пошагового выбора используем первого мастера для отображения в календаре
        first_employee_id = list(selected_employees.values())[0] if selected_employees else None

        await state.update_data(
            employee_id=first_employee_id,  # Для совместимости с календарём
            employee_name="Разные мастера",
            per_service_employees=selected_employees
        )

        # Получаем выходные дни (объединяем для всех выбранных мастеров)
        all_exclude_dates = set()
        async with async_session_maker() as session:
            for emp_id in selected_employees.values():
                exclude_dates = await get_employee_days_off_dates(emp_id, 60)
                all_exclude_dates.update(exclude_dates)

        exclude_dates_list = list(all_exclude_dates)

        price_text = f"\n💰 Общая стоимость: {total_price}₽" if total_price > 0 else ""

        today = date.today()
        await callback.message.edit_text(
            f"✅ Выбранные услуги и мастера:\n" + "\n".join(selections_text) + f"\n"
            f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
            f"📅 Выберите дату:\n"
            f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
            parse_mode="HTML",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=exclude_dates_list,
                callback_prefix="date",
                back_callback="back_to_per_service_selection"
            )
        )
        await state.set_state(BookingStates.choosing_date)
        await callback.answer()
        return

    # Ищем следующую услугу, которая требует ручного выбора (пропускаем авто-назначенные)
    manual_next_index = None
    for idx in range(next_index, len(services_for_selection)):
        svc_sel = services_for_selection[idx]
        if str(svc_sel["service_id"]) not in selected_employees:
            manual_next_index = idx
            break

    if manual_next_index is None:
        # Все оставшиеся были авто-назначены, переходим к дате
        # (повторяем логику перехода к дате из блока выше)
        services_info = data.get("services_info", [])
        total_duration = data.get("total_duration", 0)
        total_price = data.get("total_price", 0)

        async with async_session_maker() as session:
            selections_text = []
            for svc_info in services_info:
                emp_id = selected_employees.get(str(svc_info["id"]))
                if emp_id:
                    result = await session.execute(
                        select(Employee).where(Employee.id == emp_id)
                    )
                    emp = result.scalar_one_or_none()
                    emp_name = emp.name if emp else "Мастер"
                    selections_text.append(f"• {svc_info['name']} — {emp_name}")

        first_employee_id = list(selected_employees.values())[0] if selected_employees else None
        await state.update_data(
            employee_id=first_employee_id,
            employee_name="Разные мастера",
            per_service_employees=selected_employees
        )

        all_exclude_dates = set()
        async with async_session_maker() as session:
            for emp_id in selected_employees.values():
                exclude_dates = await get_employee_days_off_dates(emp_id, 60)
                all_exclude_dates.update(exclude_dates)

        price_text = f"\n💰 Общая стоимость: {total_price}₽" if total_price > 0 else ""
        today = date.today()
        await callback.message.edit_text(
            f"✅ Выбранные услуги и мастера:\n" + "\n".join(selections_text) + f"\n"
            f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
            f"📅 Выберите дату:\n"
            f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
            parse_mode="HTML",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=list(all_exclude_dates),
                callback_prefix="date",
                back_callback="back_to_per_service_selection"
            )
        )
        await state.set_state(BookingStates.choosing_date)
        await callback.answer()
        return

    # Показываем выбор мастера для следующей услуги
    await state.update_data(current_service_index=manual_next_index)

    next_service_data = services_for_selection[manual_next_index]
    next_service_id = next_service_data["service_id"]
    next_service_name = next_service_data["service_name"]
    next_employee_ids = next_service_data["employee_ids"]

    # Получаем объекты сотрудников
    async with async_session_maker() as session:
        result = await session.execute(
            select(Employee).where(Employee.id.in_(next_employee_ids))
        )
        next_employees = list(result.scalars().all())

    # Формируем текст с уже выбранными мастерами
    services_info = data.get("services_info", [])
    total_duration = data.get("total_duration", 0)
    total_price = data.get("total_price", 0)

    selected_text_parts = []
    for svc_sel in services_for_selection:
        sid = str(svc_sel["service_id"])
        if sid in selected_employees:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Employee).where(Employee.id == selected_employees[sid])
                )
                emp = result.scalar_one_or_none()
                emp_name = emp.name if emp else "?"
                selected_text_parts.append(f"✅ {svc_sel['service_name']} — {emp_name}")
        else:
            selected_text_parts.append(f"◻️ {svc_sel['service_name']}")

    price_text = f"\n💰 Общая стоимость: {total_price}₽" if total_price > 0 else ""

    await callback.message.edit_text(
        f"📋 Выбор мастеров:\n" + "\n".join(selected_text_parts) + f"\n"
        f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
        f"👤 Выберите мастера для услуги:\n<b>{next_service_name}</b>",
        parse_mode="HTML",
        reply_markup=client_kb.get_employees_for_service_keyboard(
            next_employees, next_service_id, next_service_name
        )
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_per_service_selection", BookingStates.choosing_employee_per_service)
async def cancel_per_service_selection(callback: CallbackQuery, state: FSMContext):
    """Отмена пошагового выбора мастеров"""
    data = await state.get_data()
    business_id = data["business_id"]
    business_name = data["business_name"]
    selected_service_ids = data.get("selected_service_ids", [])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        from bot.utils.business_types import is_venue_rental_type as _is_venue_cancel
        if _is_venue_cancel(business.business_type):
            services = await get_business_main_services(session, business_id)
        else:
            services = await get_business_services(session, business_id)

    await callback.message.edit_text(
        f"Выбрано: {business_name}\n\nВыберите одну или несколько услуг:",
        reply_markup=client_kb.get_services_keyboard(services, selected_ids=selected_service_ids)
    )
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


@router.callback_query(F.data == "back_to_per_service_selection")
async def back_to_per_service_selection(callback: CallbackQuery, state: FSMContext):
    """Возврат к пошаговому выбору мастеров"""
    data = await state.get_data()
    services_for_selection = data.get("services_for_selection", [])
    services_info = data.get("services_info", [])
    total_duration = data.get("total_duration", 0)
    total_price = data.get("total_price", 0)

    if not services_for_selection:
        # Если нет данных для пошагового выбора, возвращаемся к услугам
        await back_to_services(callback, state)
        return

    # Возвращаемся к выбору мастера для последней услуги
    last_index = len(services_for_selection) - 1
    await state.update_data(current_service_index=last_index)

    # Очищаем последний выбор
    selected_employees = data.get("selected_employees_per_service", {})
    last_service_id = services_for_selection[last_index]["service_id"]
    if str(last_service_id) in selected_employees:
        del selected_employees[str(last_service_id)]
    await state.update_data(selected_employees_per_service=selected_employees)

    last_service_data = services_for_selection[last_index]
    last_service_name = last_service_data["service_name"]
    last_employee_ids = last_service_data["employee_ids"]

    async with async_session_maker() as session:
        result = await session.execute(
            select(Employee).where(Employee.id.in_(last_employee_ids))
        )
        last_employees = list(result.scalars().all())

    # Формируем текст
    selected_text_parts = []
    for i, svc_info in enumerate(services_info):
        if i < last_index:
            emp_id = selected_employees.get(str(svc_info["id"]))
            if emp_id:
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(Employee).where(Employee.id == emp_id)
                    )
                    emp = result.scalar_one_or_none()
                    emp_name = emp.name if emp else "?"
                    selected_text_parts.append(f"✅ {svc_info['name']} — {emp_name}")
        else:
            selected_text_parts.append(f"◻️ {svc_info['name']}")

    price_text = f"\n💰 Общая стоимость: {total_price}₽" if total_price > 0 else ""

    await callback.message.edit_text(
        f"📋 Выбор мастеров:\n" + "\n".join(selected_text_parts) + f"\n"
        f"⏱ Общая длительность: {total_duration} мин{price_text}\n\n"
        f"👤 Выберите мастера для услуги:\n<b>{last_service_name}</b>",
        parse_mode="HTML",
        reply_markup=client_kb.get_employees_for_service_keyboard(
            last_employees, last_service_id, last_service_name
        )
    )
    await state.set_state(BookingStates.choosing_employee_per_service)
    await callback.answer()


# ===== ВЫБОР СОТРУДНИКА =====

@router.callback_query(F.data.startswith("employee:"), BookingStates.choosing_employee)
async def employee_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора сотрудника"""
    employee_data = callback.data.split(":")[1]

    if employee_data == "any":
        employee_id = None
        employee_name = "Любой мастер"
        exclude_dates = []
    else:
        employee_id = int(employee_data)
        # Получаем имя сотрудника из БД
        async with async_session_maker() as session:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            employee = result.scalar_one_or_none()
            employee_name = employee.name if employee else "Выбранный мастер"

        # Получаем выходные дни мастера
        exclude_dates = await get_employee_days_off_dates(employee_id, 60)

    await state.update_data(employee_id=employee_id, employee_name=employee_name)

    # Показываем календарь для выбора даты
    today = date.today()
    await callback.message.edit_text(
        f"👤 Мастер: {employee_name}\n\n"
        f"📅 Выберите дату:\n"
        f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
        parse_mode="HTML",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            today.year, today.month,
            exclude_dates=exclude_dates,
            callback_prefix="date",
            back_callback="back_to_employees"
        )
    )
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()


# ===== ВЫБОР ДАТЫ =====

@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    """Обработчик для некликабельных кнопок календаря"""
    await callback.answer()


@router.callback_query(F.data.startswith("cal_nav:"), BookingStates.choosing_date)
async def calendar_navigation(callback: CallbackQuery, state: FSMContext):
    """Навигация по календарю"""
    parts = callback.data.split(":")
    year = int(parts[1])
    month = int(parts[2])

    data = await state.get_data()
    venue_room_ids = data.get("venue_room_ids")

    # Режим аренды с несколькими помещениями
    if venue_room_ids:
        await callback.message.edit_text(
            f"📅 Выберите дату:",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                year, month,
                exclude_dates=[],
                callback_prefix="date",
                back_callback="back_to_services"
            )
        )
        await callback.answer()
        return

    employee_id = data.get("employee_id")
    employee_name = data.get("employee_name", "Выбранный мастер")

    # Получаем выходные дни мастера
    exclude_dates = []
    if employee_id:
        exclude_dates = await get_employee_days_off_dates(employee_id, 60)

    await callback.message.edit_text(
        f"👤 Мастер: {employee_name}\n\n"
        f"📅 Выберите дату:\n"
        f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
        parse_mode="HTML",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            year, month,
            exclude_dates=exclude_dates,
            callback_prefix="date",
            back_callback="back_to_employees"
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date:"), BookingStates.choosing_date)
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора даты"""
    date_str = callback.data.split(":", 1)[1]
    selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    await state.update_data(booking_date=date_str)

    # Получаем данные о бизнесе, сотруднике и услугах для расчета времени
    data = await state.get_data()
    business_id = data['business_id']
    employee_id = data.get('employee_id')

    # Проверяем, есть ли режим комбинированного выбора помещения+времени (аренда)
    venue_room_ids = data.get('venue_room_ids')
    if venue_room_ids:
        total_duration = data.get('total_duration', 60)
        # Загружаем помещения из БД
        async with async_session_maker() as session:
            from sqlalchemy import and_
            result = await session.execute(
                select(Employee).where(Employee.id.in_(venue_room_ids))
            )
            venue_rooms = list(result.scalars().all())
            # Сортируем в порядке venue_room_ids
            room_order = {rid: i for i, rid in enumerate(venue_room_ids)}
            venue_rooms.sort(key=lambda r: room_order.get(r.id, 0))

        # Выбираем первое помещение по умолчанию
        first_room = venue_rooms[0]
        selected_room_id = first_room.id
        await state.update_data(
            selected_venue_room_id=selected_room_id,
            employee_id=selected_room_id,
            employee_name=first_room.name
        )

        # Рассчитываем слоты для первого помещения
        available_times, occupied_times = await calculate_venue_time_slots(
            business_id, selected_room_id, selected_date, total_duration
        )

        # Инфо о выбранном зале
        _ri = []
        if first_room.capacity:
            _ri.append(f"👥 {first_room.capacity} чел.")
        if first_room.area_sqm:
            _ri.append(f"📐 {first_room.area_sqm} м²")
        _ri_line = f" ({', '.join(_ri)})" if _ri else ""
        _rd = f"\n📝 {first_room.description}" if first_room.description else ""

        await callback.message.edit_text(
            f"📅 Дата: {date_str}\n\n"
            f"🏠 Выберите зал и время:{_ri_line}{_rd}\n"
            f"🔒 - занято",
            reply_markup=client_kb.get_venue_room_time_keyboard(
                venue_rooms, selected_room_id, available_times, occupied_times
            )
        )
        await state.set_state(BookingStates.choosing_venue_room_time)
        await callback.answer()
        return

    # Получаем данные для пошагового выбора мастеров (разные мастера для разных услуг)
    per_service_employees = data.get('per_service_employees', {})
    services_info = data.get('services_info', [])

    # Используем общую длительность выбранных услуг (мультивыбор)
    service_duration = data.get('total_duration', 60)  # По умолчанию 60 минут

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

        # Определяем шаг записи
        interval = business.booking_interval_minutes
        if employee_id:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            employee = result.scalar_one_or_none()
            if employee and employee.booking_interval_minutes:
                interval = employee.booking_interval_minutes

        # Определяем время работы
        start_time = business.working_hours_start if business.working_hours_start else datetime.strptime("09:00", "%H:%M").time()
        end_time = business.working_hours_end if business.working_hours_end else datetime.strptime("18:00", "%H:%M").time()

        # Получаем существующие записи на выбранную дату для фильтрации занятых слотов
        from sqlalchemy import and_

        # Пошаговый выбор мастеров - получаем записи для ВСЕХ выбранных мастеров
        if per_service_employees:
            all_employee_ids = list(set(per_service_employees.values()))
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    and_(
                        Booking.business_id == business_id,
                        Booking.employee_id.in_(all_employee_ids),
                        Booking.booking_date == selected_date,
                        Booking.status.in_(["pending", "confirmed"])
                    )
                )
            )
            existing_bookings = result.scalars().all()
            available_employees = None
        # Если выбран конкретный мастер - фильтруем только его записи
        elif employee_id:
            # Конкретный мастер - получаем его записи
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    and_(
                        Booking.business_id == business_id,
                        Booking.employee_id == employee_id,
                        Booking.booking_date == selected_date,
                        Booking.status.in_(["pending", "confirmed"])
                    )
                )
            )
            existing_bookings = result.scalars().all()
            available_employees = None
        else:
            # "Любой мастер" - получаем всех мастеров и все записи
            result = await session.execute(
                select(Employee).where(
                    and_(
                        Employee.business_id == business_id,
                        Employee.is_active == True
                    )
                )
            )
            available_employees = result.scalars().all()

            # Получаем все записи на эту дату
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    and_(
                        Booking.business_id == business_id,
                        Booking.booking_date == selected_date,
                        Booking.status.in_(["pending", "confirmed"])
                    )
                )
            )
            existing_bookings = result.scalars().all()

    # Генерируем доступное время с учетом шага записи
    available_times = []
    occupied_times = []  # Занятые слоты для отображения
    current_time = datetime.combine(selected_date, start_time)
    end_datetime = datetime.combine(selected_date, end_time)

    # Если сегодня, начинаем с текущего времени + 1 час
    if selected_date == datetime.now().date():
        now_plus_hour = datetime.now() + timedelta(hours=1)
        if current_time < now_plus_hour:
            current_time = now_plus_hour
            # Округляем до ближайшего интервала
            minutes = (current_time.minute // interval + 1) * interval
            if minutes >= 60:
                # Используем timedelta для безопасного добавления часа (избегаем hour=24)
                current_time = current_time.replace(minute=0) + timedelta(hours=1)
            else:
                current_time = current_time.replace(minute=minutes)

    # Вспомогательная функция для проверки занятости мастера
    def is_master_busy(emp_id, check_start, check_end):
        """Проверяет, занят ли мастер в указанный промежуток времени"""
        for booking in existing_bookings:
            if booking.employee_id != emp_id:
                continue
            booking_start = datetime.combine(selected_date, booking.booking_time)
            booking_end = booking_start + timedelta(minutes=booking.service.duration_minutes)
            # Проверяем пересечение
            if not (check_end <= booking_start or check_start >= booking_end):
                return True
        return False

    # Проверяем что запись успеет завершиться до конца рабочего дня
    while current_time + timedelta(minutes=service_duration) <= end_datetime:
        # Проверяем, не попадает ли время в перерыв
        is_break = False
        if business.break_start and business.break_end:
            if business.break_start <= current_time.time() < business.break_end:
                is_break = True

        # Проверяем, не занят ли слот более чем на 30%
        slot_occupied = False
        if not is_break:
            slot_end_time = current_time + timedelta(minutes=interval)

            # ПОШАГОВЫЙ ВЫБОР МАСТЕРОВ - проверяем занятость ВСЕХ мастеров последовательно
            if per_service_employees and services_info:
                # Услуги идут последовательно: первая начинается в current_time,
                # вторая - после окончания первой, и т.д.
                service_start = current_time
                all_masters_free = True

                for svc_info in services_info:
                    svc_id = str(svc_info['id'])
                    svc_duration = svc_info.get('duration', 0)
                    emp_id = per_service_employees.get(svc_id)

                    if emp_id and svc_duration > 0:
                        service_end = service_start + timedelta(minutes=svc_duration)

                        # Проверяем что услуга успеет завершиться до конца рабочего дня
                        if service_end > end_datetime:
                            all_masters_free = False
                            break

                        # Проверяем занятость мастера на время этой услуги
                        if is_master_busy(emp_id, service_start, service_end):
                            all_masters_free = False
                            break

                        # Следующая услуга начинается сразу после этой
                        service_start = service_end

                if not all_masters_free:
                    slot_occupied = True

            elif employee_id:
                # Конкретный мастер - проверяем его занятость
                for booking in existing_bookings:
                    booking_start = datetime.combine(selected_date, booking.booking_time)
                    booking_end = booking_start + timedelta(minutes=booking.service.duration_minutes)

                    # Проверяем пересечение
                    overlap_start = max(current_time, booking_start)
                    overlap_end = min(slot_end_time, booking_end)

                    if overlap_start < overlap_end:
                        # Есть пересечение, вычисляем процент занятости
                        overlap_minutes = (overlap_end - overlap_start).total_seconds() / 60
                        occupation_percent = (overlap_minutes / interval) * 100

                        if occupation_percent > 30:
                            slot_occupied = True
                            break
            else:
                # "Любой мастер" - проверяем есть ли хотя бы один свободный
                # Проверяем что у услуги хватит времени до конца рабочего дня
                service_end_time = current_time + timedelta(minutes=service_duration)
                if service_end_time > end_datetime:
                    slot_occupied = True
                else:
                    # Проверяем каждого мастера
                    has_free_master = False
                    for emp in available_employees:
                        # Проверяем занятость этого мастера в нужном промежутке
                        master_busy = False
                        for booking in existing_bookings:
                            if booking.employee_id != emp.id:
                                continue

                            booking_start = datetime.combine(selected_date, booking.booking_time)
                            booking_end = booking_start + timedelta(minutes=booking.service.duration_minutes)

                            # Проверяем пересечение со всей длительностью услуги
                            if not (service_end_time <= booking_start or current_time >= booking_end):
                                master_busy = True
                                break

                        if not master_busy:
                            has_free_master = True
                            break

                    if not has_free_master:
                        slot_occupied = True

        if not is_break:
            if slot_occupied:
                occupied_times.append(current_time.strftime("%H:%M"))
            else:
                available_times.append(current_time.strftime("%H:%M"))

        current_time += timedelta(minutes=interval)

    await callback.message.edit_text(
        f"📅 Дата: {date_str}\n\n🕐 Выберите удобное время:\n🔒 - занято",
        reply_markup=client_kb.get_times_keyboard(available_times, occupied_times)
    )
    await state.set_state(BookingStates.choosing_time)
    await callback.answer()


# ===== ВЫБОР ВРЕМЕНИ =====

@router.callback_query(F.data.startswith("time_occupied:"), BookingStates.choosing_time)
async def occupied_time_clicked(callback: CallbackQuery):
    """Обработка клика на занятый слот времени"""
    await callback.answer("🔒 Это время уже занято. Выберите другое.", show_alert=True)


@router.callback_query(F.data.startswith("time:"), BookingStates.choosing_time)
async def time_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени"""
    time_str = callback.data.split(":")[1] + ":" + callback.data.split(":")[2]
    await state.update_data(booking_time=time_str)

    # Проверяем доп. услуги для venue_rental
    if await check_and_show_additional_services(callback, state):
        await callback.answer()
        return

    # Проверяем, есть ли у пользователя номер телефона
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

    if not user.phone:
        await callback.message.answer(
            "Для завершения записи, пожалуйста, поделитесь номером телефона:",
            reply_markup=client_kb.get_phone_request_keyboard()
        )
        await state.set_state(BookingStates.entering_phone)
    else:
        # Переходим сразу к подтверждению
        await show_confirmation(callback.message, state)

    await callback.answer()


# ===== КОМБИНИРОВАННЫЙ ВЫБОР ПОМЕЩЕНИЯ + ВРЕМЕНИ (АРЕНДА) =====

@router.callback_query(F.data.startswith("venue_room:"), BookingStates.choosing_venue_room_time)
async def venue_room_chosen(callback: CallbackQuery, state: FSMContext):
    """Переключение помещения в комбинированном виде (обновляет слоты времени)"""
    room_id = int(callback.data.split(":")[1])

    data = await state.get_data()
    business_id = data['business_id']
    date_str = data['booking_date']
    total_duration = data.get('total_duration', 60)
    venue_room_ids = data.get('venue_room_ids', [])
    selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    # Загружаем помещения из БД
    async with async_session_maker() as session:
        result = await session.execute(
            select(Employee).where(Employee.id.in_(venue_room_ids))
        )
        venue_rooms = list(result.scalars().all())
        room_order = {rid: i for i, rid in enumerate(venue_room_ids)}
        venue_rooms.sort(key=lambda r: room_order.get(r.id, 0))

        # Получаем имя выбранного помещения
        selected_room = next((r for r in venue_rooms if r.id == room_id), venue_rooms[0])

    await state.update_data(
        selected_venue_room_id=room_id,
        employee_id=room_id,
        employee_name=selected_room.name
    )

    # Пересчитываем цену при смене комнаты если время уже выбрано
    booking_time_str = data.get('booking_time')
    if booking_time_str and data.get('has_time_pricing'):
        from database.crud import calculate_time_based_price
        from datetime import time as dt_time
        t_parts = booking_time_str.split(":")
        booking_time_obj = dt_time(hour=int(t_parts[0]), minute=int(t_parts[1]))
        booking_date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
        async with async_session_maker() as session:
            time_price = await calculate_time_based_price(session, room_id, booking_time_obj, total_duration, booking_date=booking_date_obj)
        if time_price is not None and time_price > 0:
            await state.update_data(total_price=time_price, time_based_price=time_price)
        else:
            # Время не попадает в тариф — сбрасываем time_based_price, используем цену услуги
            await state.update_data(time_based_price=0)

    # Рассчитываем слоты для выбранного помещения
    available_times, occupied_times = await calculate_venue_time_slots(
        business_id, room_id, selected_date, total_duration
    )

    # Формируем инфо о выбранном зале
    room_info_parts = []
    if selected_room.capacity:
        room_info_parts.append(f"👥 {selected_room.capacity} чел.")
    if selected_room.area_sqm:
        room_info_parts.append(f"📐 {selected_room.area_sqm} м²")
    room_info_line = f" ({', '.join(room_info_parts)})" if room_info_parts else ""
    room_desc = f"\n📝 {selected_room.description}" if selected_room.description else ""

    # Предупреждение о мин. времени
    min_warn = ""
    if selected_room.min_booking_minutes and total_duration < selected_room.min_booking_minutes:
        h = selected_room.min_booking_minutes // 60
        m = selected_room.min_booking_minutes % 60
        t = f"{h}ч {m}мин" if h and m else (f"{h}ч" if h else f"{m}мин")
        min_warn = f"\n⚠️ Мин. бронирование: {t}. Выберите более длительную услугу."

    await callback.message.edit_text(
        f"📅 Дата: {date_str}\n\n"
        f"🏠 Выберите зал и время:{room_info_line}{room_desc}{min_warn}\n"
        f"🔒 - занято",
        reply_markup=client_kb.get_venue_room_time_keyboard(
            venue_rooms, room_id, available_times, occupied_times
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time_occupied:"), BookingStates.choosing_venue_room_time)
async def venue_occupied_time_clicked(callback: CallbackQuery):
    """Обработка клика на занятый слот времени в режиме аренды"""
    await callback.answer("🔒 Это время уже занято. Выберите другое.", show_alert=True)


@router.callback_query(F.data.startswith("time:"), BookingStates.choosing_venue_room_time)
async def venue_time_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени в комбинированном виде аренды"""
    time_str = callback.data.split(":")[1] + ":" + callback.data.split(":")[2]
    # Сбрасываем предыдущий расчёт при каждом новом выборе времени
    await state.update_data(booking_time=time_str, time_based_price=0)

    # Рассчитываем цену по тарифам времени (если есть)
    data = await state.get_data()

    # Проверяем, есть ли фиксированная цена у услуг (напр. уроки барабанов)
    _skip_time_pricing = False
    services_info = data.get('services_info', [])
    if services_info:
        import json as _json_mod3
        async with async_session_maker() as session:
            for svc in services_info:
                svc_obj = await get_service_by_id(session, svc['id'])
                if svc_obj and svc_obj.available_employee_ids and svc_obj.price and svc_obj.price > 0:
                    _skip_time_pricing = True
                    break

    if data.get('has_time_pricing') and not _skip_time_pricing:
        employee_id = data.get('employee_id')
        total_duration = data.get('total_duration', 60)
        from datetime import time as dt_time
        t_parts = time_str.split(":")
        booking_time_obj = dt_time(hour=int(t_parts[0]), minute=int(t_parts[1]))

        # Парсим дату для фильтрации тарифов будни/выходные
        date_str = data.get('booking_date', '')
        booking_date_obj = datetime.strptime(date_str, "%d.%m.%Y").date() if date_str else None

        from database.crud import calculate_time_based_price_detailed
        async with async_session_maker() as session:
            result = await calculate_time_based_price_detailed(session, employee_id, booking_time_obj, total_duration, booking_date=booking_date_obj)

        end_time = datetime.strptime(time_str, "%H:%M") + timedelta(minutes=total_duration)
        end_str = end_time.strftime("%H:%M")
        next_day_mark = " (+1 день)" if end_time.day > 1 else ""

        text = (
            f"💰 <b>Расчёт стоимости аренды</b>\n\n"
            f"🏠 {data.get('employee_name', 'Зал')}\n"
            f"🕐 {time_str}–{end_str}{next_day_mark} ({total_duration} мин)\n\n"
        )

        if result is not None and result["total"] > 0:
            # Время попадает в тарифную зону — показываем разбивку
            time_price = result["total"]
            await state.update_data(total_price=time_price, time_based_price=time_price)

            for seg in result["segments"]:
                hours = seg["minutes"] / 60
                if hours == int(hours):
                    hours_str = f"{int(hours)} ч"
                else:
                    hours_str = f"{seg['minutes']} мин"
                text += f"  ▪️ {seg['time_from']}–{seg['time_to']} ({hours_str}) × {seg['price_per_hour']}₽/ч = <b>{seg['subtotal']}₽</b>\n"

            text += f"\n{'━' * 20}\n💰 <b>Итого: {time_price}₽</b>"
        else:
            # Время вне тарифной зоны — стандартная цена услуги
            services_info = data.get('services_info', [])
            main_services = [s for s in services_info if not s.get('is_additional')]
            fallback_price = sum(s.get('price', 0) or 0 for s in main_services)
            await state.update_data(total_price=fallback_price, time_based_price=0)

            text += f"  ▪️ Стандартный тариф\n"
            text += f"\n{'━' * 20}\n💰 <b>Итого: {fallback_price}₽</b>"

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Продолжить", callback_data="venue_price_continue", style="success")
        builder.button(text="◀️ Выбрать другое время", callback_data=f"venue_back_to_time:{employee_id}")
        builder.adjust(1)

        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        await callback.answer()
        return

    # Нет тарифов по времени — продолжаем стандартный flow
    await _continue_after_venue_time(callback, state)
    await callback.answer()


async def _continue_after_venue_time(callback: CallbackQuery, state: FSMContext):
    """Продолжение flow после выбора времени (формат → доп. услуги → комментарий → телефон → подтверждение)"""
    data = await state.get_data()
    employee_id = data.get('employee_id')

    # Проверяем, есть ли фиксированная цена у услуг (напр. уроки барабанов)
    # Если да — пропускаем формат соло/группа
    services_info = data.get('services_info', [])
    has_fixed_price = False
    if services_info:
        import json as _json_mod2
        async with async_session_maker() as session:
            for svc in services_info:
                svc_obj = await get_service_by_id(session, svc['id'])
                if svc_obj and svc_obj.available_employee_ids and svc_obj.price and svc_obj.price > 0:
                    has_fixed_price = True
                    break

    # Проверяем, есть ли у зала solo_price_per_hour
    if employee_id and not has_fixed_price:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            emp = result.scalar_one_or_none()
            if emp and emp.solo_price_per_hour:
                # Показываем выбор формата
                total_duration = data.get('total_duration', 60)
                time_based_price = data.get('time_based_price', 0) or data.get('total_price', 0)
                solo_price = int(emp.solo_price_per_hour * total_duration / 60)
                await state.update_data(solo_price_per_hour=emp.solo_price_per_hour, solo_price=solo_price)
                await callback.message.edit_text(
                    f"🎵 <b>Выберите формат занятия</b>\n\n"
                    f"👥 <b>Группа / дуэт</b> — {time_based_price}₽\n"
                    f"👤 <b>Самостоятельно / Педагог + ученик</b> — {solo_price}₽",
                    parse_mode="HTML",
                    reply_markup=client_kb.get_booking_format_keyboard()
                )
                await state.set_state(BookingStates.choosing_booking_format)
                return

    await _continue_to_additional_or_notes(callback, state)


async def _continue_to_additional_or_notes(callback: CallbackQuery, state: FSMContext):
    """Продолжение flow: доп. услуги → комментарий → телефон → подтверждение"""
    # Проверяем доп. услуги для venue_rental
    if await check_and_show_additional_services(callback, state):
        return

    await _show_notes_step(callback.message, state)


async def _show_notes_step(message, state: FSMContext):
    """Показывает шаг ввода комментария"""
    try:
        await message.edit_text(
            "💬 Хотите добавить комментарий к записи?",
            reply_markup=client_kb.get_notes_keyboard()
        )
    except Exception:
        await message.answer(
            "💬 Хотите добавить комментарий к записи?",
            reply_markup=client_kb.get_notes_keyboard()
        )
    await state.set_state(BookingStates.entering_notes)


async def _proceed_to_phone_or_confirmation(message, state: FSMContext):
    """Проверяет телефон и переходит к подтверждению"""
    # Используем chat.id — в приватном чате это всегда telegram_id клиента.
    # message.from_user может быть ботом (если message = callback.message).
    tg_id = message.chat.id
    tg_username = message.chat.username
    tg_fullname = message.chat.full_name

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=tg_id,
            username=tg_username,
            full_name=tg_fullname
        )

    if not user.phone:
        await message.answer(
            "Для завершения записи, пожалуйста, поделитесь номером телефона:",
            reply_markup=client_kb.get_phone_request_keyboard()
        )
        await state.set_state(BookingStates.entering_phone)
    else:
        await show_confirmation(message, state, try_edit=True)


@router.callback_query(F.data == "venue_price_continue", BookingStates.choosing_venue_room_time)
async def venue_price_continue(callback: CallbackQuery, state: FSMContext):
    """Продолжить после просмотра расчёта стоимости"""
    await _continue_after_venue_time(callback, state)
    await callback.answer()


# ===== ВЫБОР ФОРМАТА (ГРУППА / СОЛО) =====

@router.callback_query(F.data.startswith("booking_format:"), BookingStates.choosing_booking_format)
async def booking_format_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора формата бронирования"""
    format_type = callback.data.split(":")[1]

    if format_type == "back":
        # Назад к экрану цены — сбрасываем solo
        await state.update_data(is_solo_booking=False)
        data = await state.get_data()
        employee_id = data.get('employee_id')
        await state.set_state(BookingStates.choosing_venue_room_time)
        # Возвращаемся к выбору времени
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Выбрать другое время", callback_data=f"venue_back_to_time:{employee_id}")
        builder.adjust(1)
        # Пересчитаем цену по venue_time_chosen
        await callback.message.edit_text(
            "◀️ Выберите другое время или вернитесь назад",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
        return

    if format_type == "solo":
        data = await state.get_data()
        solo_price = data.get('solo_price', 0)
        await state.update_data(
            is_solo_booking=True,
            time_based_price=solo_price,
            total_price=solo_price
        )
    else:
        # group — оставляем цену как есть
        await state.update_data(is_solo_booking=False)

    await _continue_to_additional_or_notes(callback, state)
    await callback.answer()


# ===== КОММЕНТАРИЙ К ЗАПИСИ =====

@router.callback_query(F.data == "booking_add_notes", BookingStates.entering_notes)
async def booking_add_notes(callback: CallbackQuery, state: FSMContext):
    """Пользователь хочет добавить комментарий"""
    await callback.message.answer("📝 Введите комментарий к записи:")
    await callback.answer()
    # Остаёмся в entering_notes — ждём текст


@router.callback_query(F.data == "booking_skip_notes", BookingStates.entering_notes)
async def booking_skip_notes(callback: CallbackQuery, state: FSMContext):
    """Пропустить комментарий"""
    await _proceed_to_phone_or_confirmation(callback.message, state)
    await callback.answer()


@router.message(F.text, BookingStates.entering_notes)
async def booking_notes_received(message: Message, state: FSMContext):
    """Получение текста комментария"""
    notes_text = message.text.strip()
    if len(notes_text) > 500:
        notes_text = notes_text[:500]
    await state.update_data(booking_notes=notes_text)
    await message.answer(f"✅ Комментарий сохранён: {notes_text}")
    await _proceed_to_phone_or_confirmation(message, state)


@router.callback_query(F.data.startswith("venue_back_to_time:"))
async def venue_back_to_time(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору времени из экрана детализации цены (работает из любого state)"""
    room_id = int(callback.data.split(":")[1])
    # Сбрасываем расчёт и возвращаем state в выбор времени
    await state.update_data(time_based_price=0)
    await state.set_state(BookingStates.choosing_venue_room_time)

    data = await state.get_data()
    business_id = data['business_id']
    date_str = data['booking_date']
    total_duration = data.get('total_duration', 60)
    venue_room_ids = data.get('venue_room_ids', [])
    selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    async with async_session_maker() as session:
        result = await session.execute(
            select(Employee).where(Employee.id.in_(venue_room_ids))
        )
        venue_rooms = list(result.scalars().all())
        room_order = {rid: i for i, rid in enumerate(venue_room_ids)}
        venue_rooms.sort(key=lambda r: room_order.get(r.id, 0))

    available_times, occupied_times = await calculate_venue_time_slots(
        business_id, room_id, selected_date, total_duration
    )

    await callback.message.edit_text(
        f"📅 Дата: {date_str}\n\n"
        f"🏠 Выберите зал и время:\n"
        f"🔒 - занято",
        reply_markup=client_kb.get_venue_room_time_keyboard(
            venue_rooms, room_id, available_times, occupied_times
        )
    )
    await callback.answer()


# ===== ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ (АРЕНДА) =====

async def check_and_show_additional_services(callback: CallbackQuery, state: FSMContext) -> bool:
    """Проверяет наличие доп. услуг для venue_rental и показывает клавиатуру выбора.
    Возвращает True если доп. услуги показаны, False если нужно продолжить обычный flow."""
    data = await state.get_data()
    business_type = data.get('business_type', '')

    from bot.utils.business_types import is_venue_rental_type
    if not is_venue_rental_type(business_type):
        return False

    # Пропускаем доп. услуги для услуг с фиксированной ценой (напр. уроки барабанов)
    services_info = data.get('services_info', [])
    if services_info:
        import json as _json_add
        async with async_session_maker() as session:
            for svc in services_info:
                svc_obj = await get_service_by_id(session, svc['id'])
                if svc_obj and svc_obj.available_employee_ids and svc_obj.price and svc_obj.price > 0:
                    return False

    business_id = data['business_id']
    async with async_session_maker() as session:
        additional_services = await get_business_additional_services(session, business_id)

    if not additional_services:
        return False

    # Сохраняем список доп. услуг в state
    add_svc_info = []
    for svc in additional_services:
        add_svc_info.append({
            'id': svc.id,
            'name': svc.name,
            'duration': svc.duration_minutes,
            'price': svc.price or 0,
            'is_hourly_price': getattr(svc, 'is_hourly_price', False)
        })
    # Вычисляем total_hours для почасовых услуг
    total_duration = data.get('total_duration', 60)
    total_hours = max(1, total_duration // 60)

    await state.update_data(
        available_additional_services=add_svc_info,
        selected_additional_service_ids=[],
        additional_service_hours={}
    )

    await callback.message.edit_text(
        "🛎 <b>Дополнительные услуги</b>\n\n"
        "Выберите дополнительные услуги или пропустите этот шаг:",
        parse_mode="HTML",
        reply_markup=client_kb.get_additional_services_keyboard(
            additional_services, [], hourly_hours={}, total_hours=total_hours
        )
    )
    await state.set_state(BookingStates.choosing_additional_services)
    return True


def _apply_additional_services_to_state(data: dict, selected_additional_ids: list) -> dict:
    """Добавляет выбранные доп. услуги в services_info и пересчитывает total_price.
    Возвращает dict с обновленными полями для state.update_data()."""
    available = data.get('available_additional_services', [])
    services_info = data.get('services_info', [])
    total_price = data.get('total_price', 0)
    total_duration = data.get('total_duration', 60)

    # Удаляем ранее добавленные доп. услуги (по is_additional флагу)
    services_info = [s for s in services_info if not s.get('is_additional')]

    # Базовая цена: из тарифов по времени или из суммы услуг
    base_price = data.get('time_based_price', 0)
    if not base_price:
        base_price = sum(s.get('price', 0) or 0 for s in services_info)
    total_price = base_price

    # Добавляем выбранные доп. услуги
    additional_service_hours = data.get('additional_service_hours', {})
    for svc in available:
        if svc['id'] in selected_additional_ids:
            svc_price = svc['price']
            is_hourly = svc.get('is_hourly_price', False)
            if is_hourly and total_duration > 0:
                # Цена за час × кол-во часов (из выбора клиента или полная длительность)
                hours = additional_service_hours.get(svc['id'], total_duration / 60)
                actual_price = int(svc_price * hours)
            else:
                hours = None
                actual_price = svc_price
            services_info.append({
                'id': svc['id'],
                'name': svc['name'],
                'duration': svc['duration'],
                'price': actual_price,
                'base_price': svc_price,
                'is_additional': True,
                'is_hourly_price': is_hourly,
                'hours': hours
            })
            total_price += actual_price

    return {
        'services_info': services_info,
        'total_price': total_price,
        'selected_additional_service_ids': selected_additional_ids
    }


@router.callback_query(F.data.startswith("add_svc:"), BookingStates.choosing_additional_services)
async def additional_service_toggled(callback: CallbackQuery, state: FSMContext):
    """Переключение выбора дополнительной услуги"""
    svc_id = int(callback.data.split(":")[1])

    data = await state.get_data()
    selected_ids = data.get('selected_additional_service_ids', [])
    hourly_hours = data.get('additional_service_hours', {})
    total_duration = data.get('total_duration', 60)
    total_hours = max(1, total_duration // 60)

    if svc_id in selected_ids:
        selected_ids.remove(svc_id)
        hourly_hours.pop(svc_id, None)
    else:
        selected_ids.append(svc_id)
        # Для почасовых — ставим дефолт = total_hours
        available = data.get('available_additional_services', [])
        for svc in available:
            if svc['id'] == svc_id and svc.get('is_hourly_price'):
                hourly_hours[svc_id] = total_hours
                break

    await state.update_data(
        selected_additional_service_ids=selected_ids,
        additional_service_hours=hourly_hours
    )

    # Обновляем клавиатуру
    business_id = data['business_id']
    async with async_session_maker() as session:
        additional_services = await get_business_additional_services(session, business_id)

    await callback.message.edit_text(
        "🛎 <b>Дополнительные услуги</b>\n\n"
        "Выберите дополнительные услуги или пропустите этот шаг:",
        parse_mode="HTML",
        reply_markup=client_kb.get_additional_services_keyboard(
            additional_services, selected_ids,
            hourly_hours=hourly_hours, total_hours=total_hours
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_svc_plus:"), BookingStates.choosing_additional_services)
async def additional_service_hours_plus(callback: CallbackQuery, state: FSMContext):
    """Увеличить кол-во часов для почасовой доп. услуги"""
    svc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    hourly_hours = data.get('additional_service_hours', {})
    total_duration = data.get('total_duration', 60)
    total_hours = max(1, total_duration // 60)

    current = hourly_hours.get(svc_id, total_hours)
    if current >= total_hours:
        await callback.answer("Максимум часов", show_alert=False)
        return

    hourly_hours[svc_id] = current + 1
    await state.update_data(additional_service_hours=hourly_hours)

    business_id = data['business_id']
    selected_ids = data.get('selected_additional_service_ids', [])
    async with async_session_maker() as session:
        additional_services = await get_business_additional_services(session, business_id)

    await callback.message.edit_reply_markup(
        reply_markup=client_kb.get_additional_services_keyboard(
            additional_services, selected_ids,
            hourly_hours=hourly_hours, total_hours=total_hours
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_svc_minus:"), BookingStates.choosing_additional_services)
async def additional_service_hours_minus(callback: CallbackQuery, state: FSMContext):
    """Уменьшить кол-во часов для почасовой доп. услуги (при 1 — убрать услугу)"""
    svc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    hourly_hours = data.get('additional_service_hours', {})
    selected_ids = data.get('selected_additional_service_ids', [])
    total_duration = data.get('total_duration', 60)
    total_hours = max(1, total_duration // 60)

    current = hourly_hours.get(svc_id, total_hours)
    if current <= 1:
        # Убираем услугу из выбора
        selected_ids = [sid for sid in selected_ids if sid != svc_id]
        hourly_hours.pop(svc_id, None)
    else:
        hourly_hours[svc_id] = current - 1

    await state.update_data(
        selected_additional_service_ids=selected_ids,
        additional_service_hours=hourly_hours
    )

    business_id = data['business_id']
    async with async_session_maker() as session:
        additional_services = await get_business_additional_services(session, business_id)

    await callback.message.edit_text(
        "🛎 <b>Дополнительные услуги</b>\n\n"
        "Выберите дополнительные услуги или пропустите этот шаг:",
        parse_mode="HTML",
        reply_markup=client_kb.get_additional_services_keyboard(
            additional_services, selected_ids,
            hourly_hours=hourly_hours, total_hours=total_hours
        )
    )
    await callback.answer()


@router.callback_query(F.data == "additional_services_done", BookingStates.choosing_additional_services)
async def additional_services_done(callback: CallbackQuery, state: FSMContext):
    """Применить выбранные доп. услуги и продолжить"""
    data = await state.get_data()
    selected_ids = data.get('selected_additional_service_ids', [])

    if not selected_ids:
        await callback.answer("Выберите хотя бы одну услугу или нажмите 'Пропустить'", show_alert=True)
        return

    # Применяем доп. услуги к state
    updates = _apply_additional_services_to_state(data, selected_ids)
    await state.update_data(**updates)

    # Переходим к комментарию
    await _show_notes_step(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "additional_services_skip", BookingStates.choosing_additional_services)
async def additional_services_skipped(callback: CallbackQuery, state: FSMContext):
    """Пропустить доп. услуги и продолжить"""
    # Убираем все доп. услуги из state (на случай если раньше были выбраны)
    data = await state.get_data()
    updates = _apply_additional_services_to_state(data, [])
    await state.update_data(**updates)

    # Переходим к комментарию
    await _show_notes_step(callback.message, state)
    await callback.answer()


# ===== ВВОД ТЕЛЕФОНА =====

@router.message(F.contact, BookingStates.entering_phone)
async def phone_received(message: Message, state: FSMContext):
    """Получение номера телефона через кнопку контакта"""
    phone = message.contact.phone_number
    # Форматируем телефон: если 10 цифр - добавляем +7
    formatted_phone = format_phone(phone)

    # Сохраняем телефон в БД
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )

        from database.crud import update_user_phone
        await update_user_phone(session, user.id, formatted_phone)

    await show_confirmation(message, state)


@router.message(F.text, BookingStates.entering_phone)
async def phone_text_received(message: Message, state: FSMContext):
    """Получение номера телефона через текстовый ввод"""
    import re

    # Извлекаем только цифры из введённого текста
    phone_digits = re.sub(r'\D', '', message.text)

    # Проверяем, что это похоже на телефон (10-11 цифр)
    if len(phone_digits) < 10 or len(phone_digits) > 12:
        await message.answer(
            "❌ Пожалуйста, введите корректный номер телефона.\n"
            "Например: +7 900 123-45-67 или 89001234567",
            reply_markup=client_kb.get_phone_request_keyboard()
        )
        return

    # Форматируем телефон
    formatted_phone = format_phone(phone_digits)

    # Сохраняем телефон в БД
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )

        from database.crud import update_user_phone
        await update_user_phone(session, user.id, formatted_phone)

    await show_confirmation(message, state)


async def show_confirmation(message: Message, state: FSMContext, try_edit: bool = False):
    """Показ экрана подтверждения записи"""
    data = await state.get_data()

    # Проверяем, есть ли пошаговый выбор мастеров
    per_service_employees = data.get('per_service_employees', {})

    # Вспомогательная функция для форматирования услуги
    def format_service_line(name, duration, price, emp_name=None):
        parts = []
        if duration and duration > 0:
            parts.append(f"{duration} мин")
        if price:
            parts.append(f"{price}₽")
        info = f" ({', '.join(parts)})" if parts else ""
        emp_part = f" — {emp_name}" if emp_name else ""
        return f"  • {name}{info}{emp_part}"

    # Формируем список услуг
    services_info = data.get('services_info', [])

    # Разделяем основные и доп. услуги
    main_services = [s for s in services_info if not s.get('is_additional')]
    additional_services = [s for s in services_info if s.get('is_additional')]

    if services_info:
        if per_service_employees:
            # Пошаговый выбор - показываем мастера для каждой услуги
            services_lines = []
            async with async_session_maker() as session:
                for s in main_services:
                    emp_id = per_service_employees.get(str(s['id']))
                    if emp_id:
                        result = await session.execute(
                            select(Employee).where(Employee.id == emp_id)
                        )
                        emp = result.scalar_one_or_none()
                        emp_name = emp.name if emp else "Мастер"
                    else:
                        emp_name = "Мастер"
                    services_lines.append(format_service_line(s['name'], s['duration'], s['price'], emp_name))
            services_text = "\n".join(services_lines)
            master_text = ""  # Не показываем отдельную строку мастера
        else:
            services_text = "\n".join([format_service_line(s['name'], s['duration'], s['price']) for s in main_services])
            master_text = f"👤 Мастер: {data['employee_name']}\n"

        # Добавляем доп. услуги отдельным блоком
        if additional_services:
            add_lines = []
            for s in additional_services:
                if s.get('is_hourly_price') and s.get('base_price'):
                    hours = s.get('hours') or (data.get('total_duration', 60) / 60)
                    if hours == int(hours):
                        hours_str = f"{int(hours)}ч"
                    else:
                        hours_str = f"{hours:.1f}ч"
                    add_lines.append(f"  • {s['name']} ({s['base_price']}₽/ч x {hours_str} = {s['price']}₽)")
                else:
                    add_lines.append(format_service_line(s['name'], 0, s['price']))
            additional_text = "\n🛎 Доп. услуги:\n" + "\n".join(add_lines)
            services_text += additional_text

        total_duration = data.get('total_duration', 0)
        total_price = data.get('total_price', 0)
        price_text = f"💰 Общая стоимость: {total_price}₽\n" if total_price > 0 else ""
    else:
        # Обратная совместимость со старым форматом (одна услуга)
        services_text = format_service_line(data['service_name'], data['service_duration'], data.get('service_price'))
        total_duration = data['service_duration']
        total_price = data.get('service_price', 0)
        price_text = f"💰 Цена: {total_price}₽\n" if total_price else ""
        master_text = f"👤 Мастер: {data['employee_name']}\n"

    # Формируем строку длительности (скрываем если 0)
    duration_text = f"⏱ Длительность: {total_duration} мин\n" if total_duration and total_duration > 0 else ""

    # Формируем время с окончанием (10.00-11.00)
    booking_time_str = data['booking_time']
    if total_duration and total_duration > 0:
        start_time = datetime.strptime(booking_time_str, "%H:%M")
        end_time = start_time + timedelta(minutes=total_duration)
        next_day_mark = " (+1 день)" if end_time.day > start_time.day else ""
        time_display = f"{start_time.strftime('%H.%M')}-{end_time.strftime('%H.%M')}{next_day_mark}"
    else:
        time_display = booking_time_str.replace(":", ".")

    # Формат занятия (solo/group)
    format_text = ""
    if data.get('is_solo_booking'):
        format_text = "🎵 Формат: Самостоятельно / Педагог + ученик\n"

    # Комментарий
    notes_text = ""
    if data.get('booking_notes'):
        notes_text = f"💬 Комментарий: {data['booking_notes']}\n"

    # Получаем owner_username для venue_rental
    owner_username = None
    from bot.utils.business_types import is_venue_rental_type as _is_venue_conf
    if _is_venue_conf(data.get('business_type')):
        async with async_session_maker() as session:
            business_obj = await get_business_by_id(session, data['business_id'])
            if business_obj and business_obj.owner and business_obj.owner.username:
                owner_username = business_obj.owner.username

    contact_text = ""
    if owner_username:
        contact_text = f'\n💬 <a href="https://t.me/{owner_username}">Связаться с владельцем</a>\n'

    confirmation_text = f"""
📋 <b>Подтверждение записи</b>

🏢 Заведение: {data['business_name']}
💼 Услуги:
{services_text}
{duration_text}{price_text}{master_text}{format_text}{notes_text}📅 Дата: {data['booking_date']}
🕐 Время: {time_display}
{contact_text}
Подтверждаете запись?
"""

    if try_edit:
        try:
            await message.edit_text(
                confirmation_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=client_kb.get_confirmation_keyboard()
            )
            await state.set_state(BookingStates.confirming)
            return
        except Exception:
            pass

    await message.answer(
        confirmation_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=client_kb.get_confirmation_keyboard()
    )
    await state.set_state(BookingStates.confirming)


# ===== ПОДТВЕРЖДЕНИЕ ЗАПИСИ =====

@router.callback_query(F.data == "confirm_change_datetime", BookingStates.confirming)
async def confirm_change_datetime(callback: CallbackQuery, state: FSMContext):
    """Изменить дату и время из экрана подтверждения — переходим к календарю"""
    # Сбрасываем промежуточные данные (формат, комментарий, доп. услуги)
    await state.update_data(
        is_solo_booking=False,
        booking_notes=None,
        selected_additional_service_ids=[],
        additional_service_hours={},
    )
    data = await state.get_data()
    venue_room_ids = data.get("venue_room_ids")

    if venue_room_ids:
        # Venue rental — показываем календарь
        today = date.today()
        await callback.message.edit_text(
            f"📅 Выберите дату:",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=[],
                callback_prefix="date",
                back_callback="back_to_services"
            )
        )
        await state.set_state(BookingStates.choosing_date)
    else:
        employee_id = data.get("employee_id")
        exclude_dates = []
        if employee_id:
            exclude_dates = await get_employee_days_off_dates(employee_id, 60)

        today = date.today()
        employee_name = data.get("employee_name", "Мастер")
        await callback.message.edit_text(
            f"👤 Мастер: {employee_name}\n\n"
            f"📅 Выберите дату:\n"
            f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
            parse_mode="HTML",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=exclude_dates,
                callback_prefix="date",
                back_callback="back_to_employees"
            )
        )
        await state.set_state(BookingStates.choosing_date)
    await callback.answer()


@router.callback_query(F.data == "confirm_booking", BookingStates.confirming)
async def booking_confirmed(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и создание записи"""
    # Сразу отвечаем на callback - защита от двойного клика
    await callback.answer()

    data = await state.get_data()

    # Парсим дату и время
    booking_date = datetime.strptime(data['booking_date'], "%d.%m.%Y").date()
    booking_time = datetime.strptime(data['booking_time'], "%H:%M").time()

    async with async_session_maker() as session:
        # Получаем пользователя
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        try:
            # Получаем информацию о выбранных услугах
            services_info = data.get('services_info', [])

            # Если выбран "любой мастер", находим свободного
            assigned_employee_id = data.get('employee_id')
            if not assigned_employee_id:
                # Получаем всех активных мастеров бизнеса
                from sqlalchemy import and_
                result = await session.execute(
                    select(Employee).where(
                        and_(
                            Employee.business_id == data['business_id'],
                            Employee.is_active == True
                        )
                    )
                )
                all_employees = result.scalars().all()

                # Получаем существующие записи на выбранную дату
                result = await session.execute(
                    select(Booking)
                    .options(selectinload(Booking.service))
                    .where(
                        and_(
                            Booking.business_id == data['business_id'],
                            Booking.booking_date == booking_date,
                            Booking.status.in_(["pending", "confirmed"])
                        )
                    )
                )
                existing_bookings_list = result.scalars().all()

                # Вычисляем общую длительность всех услуг
                total_duration_minutes = data.get('total_duration', 0)
                if not total_duration_minutes and services_info:
                    total_duration_minutes = sum(s['duration'] for s in services_info)
                elif not total_duration_minutes:
                    total_duration_minutes = data.get('service_duration', 60)

                # Ищем свободного мастера
                for emp in all_employees:
                    is_free = True
                    check_time = booking_time
                    end_time = (datetime.combine(booking_date, booking_time) + timedelta(minutes=total_duration_minutes)).time()

                    for booking in existing_bookings_list:
                        if booking.employee_id != emp.id:
                            continue

                        booking_start = booking.booking_time
                        booking_end = (datetime.combine(booking_date, booking.booking_time) +
                                       timedelta(minutes=booking.service.duration_minutes)).time()

                        # Проверяем пересечение
                        if not (end_time <= booking_start or check_time >= booking_end):
                            is_free = False
                            break

                    if is_free:
                        assigned_employee_id = emp.id
                        break

            # Если есть несколько услуг, создаем запись для каждой
            if services_info:
                created_bookings = []
                current_time = booking_time

                # Проверяем, есть ли пошаговый выбор мастеров (разные мастера для разных услуг)
                per_service_employees = data.get('per_service_employees', {})

                # Находим employee_id основной услуги (для доп. услуг)
                main_service_employee_id = assigned_employee_id
                if per_service_employees:
                    # Ищем первую основную услугу (не is_additional) и берём её мастера
                    for s in services_info:
                        if not s.get('is_additional'):
                            main_service_employee_id = per_service_employees.get(str(s['id']), assigned_employee_id)
                            break

                for service_info in services_info:
                    # Определяем мастера для данной услуги
                    if service_info.get('is_additional'):
                        # Доп. услуги ВСЕГДА используют того же мастера/помещение, что и основная услуга
                        service_employee_id = main_service_employee_id
                    elif per_service_employees:
                        # Пошаговый выбор - разные мастера для разных услуг
                        service_employee_id = per_service_employees.get(str(service_info['id']), assigned_employee_id)
                    else:
                        # Стандартный выбор - один мастер для всех услуг
                        service_employee_id = assigned_employee_id

                    # Создаем запись для каждой услуги
                    booking = await create_booking(
                        session,
                        business_id=data['business_id'],
                        client_id=user.id,
                        service_id=service_info['id'],
                        booking_date=booking_date,
                        booking_time=current_time,
                        employee_id=service_employee_id,
                        notes=data.get('booking_notes') if len(created_bookings) == 0 else None
                    )
                    created_bookings.append(booking)

                    # Доп. услуги (is_additional) не сдвигают время
                    if not service_info.get('is_additional'):
                        current_datetime = datetime.combine(booking_date, current_time)
                        current_datetime += timedelta(minutes=service_info['duration'])
                        current_time = current_datetime.time()

                # Подгружаем relationships для первой записи (для уведомлений)
                result = await session.execute(
                    select(Booking)
                    .options(
                        selectinload(Booking.business).selectinload(Business.owner),
                        selectinload(Booking.service),
                        selectinload(Booking.employee),
                        selectinload(Booking.client)
                    )
                    .where(Booking.id == created_bookings[0].id)
                )
                booking = result.scalar_one()
            else:
                # Обратная совместимость - одна услуга (старый формат)
                booking = await create_booking(
                    session,
                    business_id=data['business_id'],
                    client_id=user.id,
                    service_id=data['service_id'],
                    booking_date=booking_date,
                    booking_time=booking_time,
                    employee_id=data.get('employee_id'),
                    notes=data.get('booking_notes')
                )

                # Подгружаем все необходимые relationships для использования вне сессии
                result = await session.execute(
                    select(Booking)
                    .options(
                        selectinload(Booking.business).selectinload(Business.owner),
                        selectinload(Booking.service),
                        selectinload(Booking.employee),
                        selectinload(Booking.client)
                    )
                    .where(Booking.id == booking.id)
                )
                booking = result.scalar_one()

            # Получаем информацию о бизнесе для ссылок
            from database.crud import get_business_by_id
            business = await get_business_by_id(session, data['business_id'])

            # Проверяем, используется ли абонемент
            use_subscription = data.get('use_subscription', False)
            subscription_usage = None

            if use_subscription:
                client_sub_id = data.get('client_subscription_id')
                if client_sub_id and services_info:
                    # Используем услугу из абонемента
                    for service_info in services_info:
                        usage = await use_subscription_service(
                            session,
                            client_subscription_id=client_sub_id,
                            service_id=service_info['id'],
                            booking_id=created_bookings[0].id if created_bookings else booking.id
                        )
                        if usage:
                            subscription_usage = usage
                            # Связываем бронирование с использованием абонемента
                            if created_bookings:
                                created_bookings[0].subscription_usage_id = usage.id
                            else:
                                booking.subscription_usage_id = usage.id
                            await session.commit()

                # Если использован абонемент - пропускаем предоплату
                # и сразу показываем успешное сообщение
                subscription_name = data.get('subscription_name', 'Абонемент')

                # Формируем сообщение
                confirm_text = (
                    f"✅ <b>Запись успешно создана!</b>\n\n"
                    f"🎫 <b>Оплачено по абонементу: {subscription_name}</b>\n\n"
                    f"🏢 {data['business_name']}\n"
                    f"📅 {data['booking_date']} в {data['booking_time']}\n"
                )

                if services_info:
                    confirm_text += "\n📋 <b>Услуги:</b>\n"
                    for svc in services_info:
                        confirm_text += f"  • {svc['name']}\n"

                if booking.employee:
                    confirm_text += f"\n👤 {booking.employee.name}"

                show_admin, show_master = await get_user_roles(callback.from_user.id)
                await callback.message.edit_text(
                    confirm_text,
                    parse_mode="HTML"
                )
                await callback.message.answer(
                    "Вы получите напоминание за 24 часа и за 2 часа до записи.",
                    reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
                )

                # Отправляем уведомления
                from bot.services.notifications import notify_master_new_booking, notify_owner_new_booking, notify_administrator_new_booking

                try:
                    await notify_master_new_booking(callback.bot, booking, services_info, is_subscription=True, subscription_name=subscription_name)
                except:
                    pass

                try:
                    await notify_owner_new_booking(callback.bot, booking, services_info, is_subscription=True, subscription_name=subscription_name)
                except:
                    pass

                try:
                    await notify_administrator_new_booking(callback.bot, booking, services_info, is_subscription=True, subscription_name=subscription_name)
                except:
                    pass

                await state.clear()
                return

            # Проверяем, требуется ли предоплата
            if business.prepayment_enabled and business.payment_phone:
                # Рассчитываем сумму предоплаты
                total_price = data.get('total_price', 0)
                if not total_price and services_info:
                    total_price = sum(s.get('price', 0) or 0 for s in services_info)

                if total_price > 0:
                    prepayment_percent = business.prepayment_percent or 100
                    prepayment_amount = int(total_price * prepayment_percent / 100)

                    # Обновляем статус бронирований на "pending_prepayment"
                    if services_info and len(created_bookings) > 0:
                        for bk in created_bookings:
                            bk.status = "pending_prepayment"
                            bk.prepayment_amount = prepayment_amount
                        await session.commit()
                        first_booking_id = created_bookings[0].id
                    else:
                        booking.status = "pending_prepayment"
                        booking.prepayment_amount = prepayment_amount
                        await session.commit()
                        first_booking_id = booking.id

                    # Формируем сообщение о предоплате
                    prepay_text = (
                        f"💳 <b>Требуется предоплата</b>\n\n"
                        f"🏢 {data['business_name']}\n"
                        f"📅 {data['booking_date']} в {data['booking_time']}\n\n"
                        f"💰 <b>Сумма предоплаты: {prepayment_amount}₽</b>"
                    )
                    if prepayment_percent < 100:
                        prepay_text += f" ({prepayment_percent}% от {total_price}₽)"

                    prepay_text += f"\n\n📱 <b>Перевести на номер:</b> {business.payment_phone}"

                    if business.payment_details:
                        prepay_text += f"\n📝 <b>Реквизиты:</b> {business.payment_details}"

                    prepay_text += (
                        f"\n\n⚠️ После отправки оплаты нажмите кнопку "
                        f"<b>'Оплата отправлена'</b>.\n"
                        f"Бронирование будет подтверждено после проверки оплаты владельцем."
                    )

                    await callback.message.edit_text(
                        prepay_text,
                        parse_mode="HTML",
                        reply_markup=client_kb.get_prepayment_confirmation_keyboard(first_booking_id)
                    )

                    await state.set_state(BookingStates.waiting_prepayment)
                    return

        except ValueError as e:
            # Время уже занято или дубликат
            show_admin, show_master = await get_user_roles(callback.from_user.id)
            await callback.message.edit_text(
                f"😔 К сожалению, {str(e)}.\n\nПожалуйста, выберите другое время 🙏",
                reply_markup=None
            )
            await callback.message.answer(
                "😊 Попробуйте записаться снова:",
                reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
            )
            await state.clear()
            return

    # Отправляем уведомления (после закрытия сессии, но с подгруженными данными)
    from bot.services.notifications import notify_master_new_booking, notify_owner_new_booking, notify_administrator_new_booking

    # Передаем список услуг с информацией о мастерах
    services_info = data.get('services_info', [])
    per_service_employees = data.get('per_service_employees', {})

    # Если есть пошаговый выбор мастеров - добавляем информацию о мастерах в services_info
    if services_info and per_service_employees:
        async with async_session_maker() as session:
            services_info_with_employees = []
            for svc in services_info:
                svc_copy = svc.copy()
                emp_id = per_service_employees.get(str(svc['id']))
                if emp_id:
                    result = await session.execute(
                        select(Employee).where(Employee.id == emp_id)
                    )
                    emp = result.scalar_one_or_none()
                    if emp:
                        svc_copy['employee_id'] = emp.id
                        svc_copy['employee_name'] = emp.name
                        svc_copy['employee_telegram_id'] = emp.telegram_id
                services_info_with_employees.append(svc_copy)
            services_info = services_info_with_employees

    await notify_master_new_booking(callback.bot, booking, services_info if services_info else None)
    await notify_owner_new_booking(callback.bot, booking, services_info if services_info else None)
    await notify_administrator_new_booking(callback.bot, booking, services_info if services_info else None)

    # Формируем кликабельные ссылки
    phone_text = ""
    if business.phone:
        formatted_phone = format_phone(business.phone)
        tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
        phone_text = f'\n📞 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>'

    address_text = ""
    if business.address:
        from urllib.parse import quote
        encoded_address = quote(business.address)
        yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
        address_text = f'\n📍 Адрес: <a href="{yandex_maps_url}">{business.address}</a>'

    # Определяем текст о напоминании в зависимости от времени до записи
    booking_datetime = datetime.combine(booking_date, booking_time)
    now = datetime.now()
    time_until_booking = booking_datetime - now

    if time_until_booking.total_seconds() < 24 * 3600:  # Меньше 24 часов
        reminder_text = "Мы отправим вам напоминание за 2 часа до визита."
    else:
        reminder_text = "Мы отправим вам напоминание за день и за 2 часа до визита."

    # Формируем текст с услугами и ценами
    services_info = data.get('services_info', [])
    if services_info:
        main_svcs = [s for s in services_info if not s.get('is_additional')]
        add_svcs = [s for s in services_info if s.get('is_additional')]
        services_text = "\n".join([
            f"  • {s['name']}{f' - {s["price"]}₽' if s.get('price') else ''}"
            for s in main_svcs
        ])
        if add_svcs:
            services_text += "\n🛎 Доп. услуги:\n" + "\n".join([
                f"  • {s['name']}{f' - {s["price"]}₽' if s.get('price') else ''}"
                for s in add_svcs
            ])
        total_price = data.get('total_price', 0)
        price_line = f"\n💰 Итого: {total_price}₽" if total_price > 0 else ""
        services_display = f"💼 Услуги:\n{services_text}{price_line}"
    else:
        price_part = f" - {data.get('service_price')}₽" if data.get('service_price') else ""
        services_display = f"💼 {data['service_name']}{price_part}"

    confirmation_text = f"""
✅ <b>Запись успешно создана!</b>

📅 {data['booking_date']} в {data['booking_time']}
🏢 {data['business_name']}
{services_display}
{address_text}
{phone_text}

{reminder_text}
"""

    # Проверяем наличие фото и инструкций для кнопок
    import json
    has_photos = False
    has_directions = False

    if business.photos:
        try:
            photos_data = json.loads(business.photos)
            has_photos = len(photos_data) > 0
        except:
            pass

    has_directions = business.directions is not None and business.directions.strip() != ""

    # Создаем клавиатуру с кнопками просмотра информации
    info_keyboard = None
    if has_photos or has_directions:
        info_keyboard = client_kb.get_business_info_keyboard(
            business_id=business.id,
            has_photos=has_photos,
            has_directions=has_directions
        )

    await callback.message.edit_text(
        confirmation_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=info_keyboard
    )

    # Отправляем клиентское меню
    show_admin, show_master = await get_user_roles(callback.from_user.id)
    await callback.message.answer(
        "Что хотите сделать дальше?",
        reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
    )

    await state.clear()


@router.callback_query(F.data == "cancel_booking", BookingStates.confirming)
async def booking_cancelled(callback: CallbackQuery, state: FSMContext):
    """Отмена создания записи"""
    show_admin, show_master = await get_user_roles(callback.from_user.id)
    await callback.message.edit_text("❌ Запись отменена")
    await callback.message.answer(
        "😊 Что хотите сделать?",
        reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
    )
    await state.clear()
    await callback.answer()


# ===== ПРОСМОТР ЗАПИСЕЙ =====

BOOKINGS_PER_PAGE = 10


def group_bookings(bookings: list) -> list:
    """Группирует записи по визитам (одна дата + бизнес + последовательное время).

    Записи считаются одним визитом если:
    - Одна дата
    - Один бизнес
    - Идут последовательно по времени (конец одной = начало следующей)

    Returns:
        list of lists: каждый элемент - список записей одного визита
    """
    if not bookings:
        return []

    # Сортируем по дате, бизнесу и времени
    sorted_bookings = sorted(bookings, key=lambda b: (b.booking_date, b.business_id, b.booking_time))

    groups = []
    current_group = [sorted_bookings[0]]

    for i in range(1, len(sorted_bookings)):
        prev = sorted_bookings[i - 1]
        curr = sorted_bookings[i]

        # Проверяем, является ли это продолжением визита
        same_date = prev.booking_date == curr.booking_date
        same_business = prev.business_id == curr.business_id

        # Вычисляем ожидаемое время начала следующей услуги
        prev_end = datetime.combine(prev.booking_date, prev.booking_time) + timedelta(minutes=prev.service.duration_minutes)
        curr_start = datetime.combine(curr.booking_date, curr.booking_time)

        # Допускаем погрешность в 5 минут
        is_sequential = abs((curr_start - prev_end).total_seconds()) <= 300

        if same_date and same_business and is_sequential:
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]

    groups.append(current_group)
    return groups


def build_bookings_page(active_bookings: list, page: int = 0) -> tuple:
    """Формирует текст и клавиатуру для страницы записей (группирует по визитам)

    Returns:
        tuple: (text, keyboard, total_pages)
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    import json

    # Группируем записи по визитам
    booking_groups = group_bookings(active_bookings)

    total = len(booking_groups)
    total_pages = max(1, (total + BOOKINGS_PER_PAGE - 1) // BOOKINGS_PER_PAGE)
    start = page * BOOKINGS_PER_PAGE
    end = min(start + BOOKINGS_PER_PAGE, total)

    page_groups = booking_groups[start:end]

    text = f"📅 <b>Активные записи</b>"
    if total_pages > 1:
        text += f" (стр. {page + 1}/{total_pages})"
    text += ":\n\n"

    for group in page_groups:
        first_booking = group[0]
        status_emoji = "⏳" if first_booking.status == "pending" else "✅"
        text += f"{status_emoji} <b>{format_date_with_weekday(first_booking.booking_date)} в {first_booking.booking_time.strftime('%H:%M')}</b>\n"
        text += f"🏢 {first_booking.business.name}\n"

        # Показываем все услуги визита
        if len(group) > 1:
            text += f"💼 Услуги ({len(group)}):\n"
            for b in group:
                text += f"   • {b.service.name}\n"
        else:
            text += f"💼 {first_booking.service.name}\n"

        if first_booking.employee:
            text += f"👤 {first_booking.employee.name}\n"
        text += "\n"

    builder = InlineKeyboardBuilder()

    # Группируем записи по бизнесам для кнопок просмотра информации
    businesses_with_bookings = {}
    for group in page_groups:
        booking = group[0]
        if booking.business_id not in businesses_with_bookings:
            businesses_with_bookings[booking.business_id] = booking.business

    # Добавляем кнопки для просмотра информации о каждом бизнесе
    for business_id, business in businesses_with_bookings.items():
        has_photos = False
        has_directions = False
        has_contacts = business.phone or business.address

        if business.photos:
            try:
                photos_data = json.loads(business.photos)
                has_photos = len(photos_data) > 0
            except:
                pass

        has_directions = business.directions is not None and business.directions.strip() != ""

        if has_photos or has_directions or has_contacts:
            builder.button(
                text=f"ℹ️ Информация: {business.name}",
                callback_data=f"booking_business_info:{business_id}"
            )

    # Добавляем кнопки управления для каждого визита (по первой записи группы)
    for group in page_groups:
        first_booking = group[0]
        services_count = f" ({len(group)} усл.)" if len(group) > 1 else ""
        btn_text = f"📝 {format_date_with_weekday(first_booking.booking_date, short=True)} {first_booking.booking_time.strftime('%H:%M')}{services_count}"
        builder.button(text=btn_text, callback_data=f"booking_details:{first_booking.id}")

    # Кнопки навигации
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(("◀️", f"my_bookings_page:{page-1}"))
        nav_row.append((f"{page+1}/{total_pages}", "noop"))
        if page < total_pages - 1:
            nav_row.append(("▶️", f"my_bookings_page:{page+1}"))

        for text_btn, callback in nav_row:
            builder.button(text=text_btn, callback_data=callback)

    builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")

    # Настройка раскладки
    adjust = [1] * (len(businesses_with_bookings) + len(page_groups))
    if total_pages > 1:
        adjust.append(len([x for x in [page > 0, True, page < total_pages - 1] if x]))
    adjust.append(1)
    builder.adjust(*adjust)

    return text, builder.as_markup(), total_pages


@router.message(F.text == "📋 Мои записи")
async def show_my_bookings(message: Message):
    """Показать записи пользователя"""
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )

        bookings = await get_user_bookings(session, user.id)

    show_admin, show_master = await get_user_roles(message.from_user.id)
    reply_keyboard = client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)

    if not bookings:
        await message.answer(
            "📭 У вас пока нет записей.\n\nНажмите «📅 Записаться», чтобы создать первую! 😊",
            reply_markup=reply_keyboard
        )
        return

    from datetime import datetime
    now = datetime.now()

    active_bookings = []
    for b in bookings:
        if b.status in ["pending", "confirmed"]:
            booking_datetime = datetime.combine(b.booking_date, b.booking_time)
            if booking_datetime > now:
                active_bookings.append(b)

    if active_bookings:
        text, keyboard, _ = build_bookings_page(active_bookings, page=0)

        await message.answer(
            "📍 Кнопки переключения режимов внизу ⬇️",
            reply_markup=reply_keyboard
        )
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer("📭 У вас нет активных записей.\n\nСамое время записаться! 😊", reply_markup=reply_keyboard)


@router.callback_query(F.data.startswith("my_bookings_page:"))
async def my_bookings_pagination(callback: CallbackQuery):
    """Пагинация списка записей клиента"""
    page = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )
        bookings = await get_user_bookings(session, user.id)

    from datetime import datetime
    now = datetime.now()

    active_bookings = []
    for b in bookings:
        if b.status in ["pending", "confirmed"]:
            booking_datetime = datetime.combine(b.booking_date, b.booking_time)
            if booking_datetime > now:
                active_bookings.append(b)

    if active_bookings:
        text, keyboard, _ = build_bookings_page(active_bookings, page=page)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


# ===== НАВИГАЦИЯ НАЗАД =====

@router.callback_query(F.data == "back_to_businesses")
async def back_to_businesses(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору бизнеса"""
    async with async_session_maker() as session:
        businesses = await get_all_active_businesses(session)

    await callback.message.edit_text(
        "🏢 Выберите заведение:",
        reply_markup=client_kb.get_businesses_keyboard(businesses)
    )
    await state.set_state(BookingStates.choosing_business)
    await callback.answer()


@router.callback_query(F.data == "back_to_services")
async def back_to_services(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору услуги"""
    data = await state.get_data()
    business_id = data["business_id"]
    business_name = data["business_name"]
    selected_service_ids = data.get("selected_service_ids", [])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)
        from bot.utils.business_types import is_venue_rental_type as _is_venue_back
        if _is_venue_back(business.business_type):
            services = await get_business_main_services(session, business_id)
        else:
            services = await get_business_services(session, business_id)

    await callback.message.edit_text(
        f"Выбрано: {business_name}\n\nВыберите одну или несколько услуг:",
        reply_markup=client_kb.get_services_keyboard(services, selected_ids=selected_service_ids)
    )
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


@router.callback_query(F.data == "back_to_employees")
async def back_to_employees(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору сотрудника"""
    data = await state.get_data()
    business_id = data["business_id"]
    selected_service_ids = data.get("selected_service_ids", [])

    async with async_session_maker() as session:
        all_employees = await get_business_employees(session, business_id)
        all_employees = [e for e in all_employees if e.role in ("master", "master_and_admin")]

        # Фильтруем мастеров по услугам
        employees = []
        for emp in all_employees:
            emp_service_ids = await get_employee_service_ids(session, emp.id)
            if not emp_service_ids:
                # Если у мастера нет назначенных услуг - он может делать всё
                employees.append(emp)
            elif all(sid in emp_service_ids for sid in selected_service_ids):
                # Мастер может делать все выбранные услуги
                employees.append(emp)

    await callback.message.edit_text(
        "👤 Выберите специалиста:",
        reply_markup=client_kb.get_employees_keyboard(employees)
    )
    await state.set_state(BookingStates.choosing_employee)
    await callback.answer()


@router.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору даты"""
    data = await state.get_data()
    venue_room_ids = data.get("venue_room_ids")

    # Режим аренды с несколькими помещениями — назад к календарю без привязки к мастеру
    if venue_room_ids:
        today = date.today()
        await callback.message.edit_text(
            f"📅 Выберите дату:",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=[],
                callback_prefix="date",
                back_callback="back_to_services"
            )
        )
        await state.set_state(BookingStates.choosing_date)
        await callback.answer()
        return

    employee_id = data.get("employee_id")
    employee_name = data.get("employee_name", "Выбранный мастер")

    # Получаем выходные дни мастера (если выбран конкретный мастер)
    exclude_dates = []
    if employee_id:
        exclude_dates = await get_employee_days_off_dates(employee_id, 60)

    # Показываем календарь
    today = date.today()
    await callback.message.edit_text(
        f"👤 Мастер: {employee_name}\n\n"
        f"📅 Выберите дату:\n"
        f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
        parse_mode="HTML",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            today.year, today.month,
            exclude_dates=exclude_dates,
            callback_prefix="date",
            back_callback="back_to_employees"
        )
    )
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()


@router.callback_query(F.data == "back_to_times")
async def back_to_times(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору времени"""
    data = await state.get_data()
    venue_room_ids = data.get("venue_room_ids")

    # Режим аренды с несколькими помещениями — возврат к комбинированному виду
    if venue_room_ids:
        date_str = data.get("booking_date")
        business_id = data.get("business_id")
        total_duration = data.get("total_duration", 60)
        selected_room_id = data.get("selected_venue_room_id", venue_room_ids[0])
        selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()

        # Загружаем помещения
        async with async_session_maker() as session:
            result = await session.execute(
                select(Employee).where(Employee.id.in_(venue_room_ids))
            )
            venue_rooms = list(result.scalars().all())
            room_order = {rid: i for i, rid in enumerate(venue_room_ids)}
            venue_rooms.sort(key=lambda r: room_order.get(r.id, 0))

        available_times, occupied_times = await calculate_venue_time_slots(
            business_id, selected_room_id, selected_date, total_duration
        )

        await callback.message.edit_text(
            f"📅 Дата: {date_str}\n\n"
            f"🏠 Выберите зал и время:\n"
            f"🔒 - занято",
            reply_markup=client_kb.get_venue_room_time_keyboard(
                venue_rooms, selected_room_id, available_times, occupied_times
            )
        )
        await state.set_state(BookingStates.choosing_venue_room_time)
        await callback.answer()
        return

    selected_date = data.get("selected_date")
    service_id = data.get("service_id")
    employee_id = data.get("employee_id")
    business_id = data.get("business_id")

    selected_date_obj = datetime.strptime(selected_date, "%d.%m.%Y").date() if isinstance(selected_date, str) else selected_date

    async with async_session_maker() as session:
        from database.crud import get_service_by_id, get_business_by_id
        service = await get_service_by_id(session, service_id)

        if not service:
            await callback.answer("Ошибка: услуга не найдена", show_alert=True)
            return

        business = service.business
        service_duration = service.duration_minutes

        # Определяем шаг записи
        interval = business.booking_interval_minutes
        if employee_id:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            employee = result.scalar_one_or_none()
            if employee and employee.booking_interval_minutes:
                interval = employee.booking_interval_minutes

        # Определяем время работы
        start_time = business.working_hours_start if business.working_hours_start else datetime.strptime("09:00", "%H:%M").time()
        end_time = business.working_hours_end if business.working_hours_end else datetime.strptime("18:00", "%H:%M").time()

        # Получаем существующие бронирования на эту дату
        result = await session.execute(
            select(Booking)
            .options(selectinload(Booking.service))
            .where(
                and_(
                    Booking.business_id == business_id,
                    Booking.booking_date == selected_date_obj,
                    Booking.status.in_(["pending", "confirmed"])
                )
            )
        )
        existing_bookings = result.scalars().all()

        # Получаем всех активных сотрудников (для режима "любой мастер")
        result = await session.execute(
            select(Employee).where(
                and_(
                    Employee.business_id == business_id,
                    Employee.is_active == True
                )
            )
        )
        available_employees = result.scalars().all()

    # Генерируем доступное время с учетом длительности услуги
    available_times = []
    occupied_times = []
    current_time = datetime.combine(selected_date_obj, start_time)
    end_datetime = datetime.combine(selected_date_obj, end_time)

    # Если сегодня, начинаем с текущего времени + 1 час
    if selected_date_obj == datetime.now().date():
        now_plus_hour = datetime.now() + timedelta(hours=1)
        if current_time < now_plus_hour:
            current_time = now_plus_hour
            # Округляем до ближайшего интервала
            minutes = (current_time.minute // interval + 1) * interval
            if minutes >= 60:
                current_time = current_time.replace(minute=0) + timedelta(hours=1)
            else:
                current_time = current_time.replace(minute=minutes)

    # Проверяем что запись успеет завершиться до конца рабочего дня
    while current_time + timedelta(minutes=service_duration) <= end_datetime:
        # Проверяем, не попадает ли время в перерыв
        is_break = False
        if business.break_start and business.break_end:
            if business.break_start <= current_time.time() < business.break_end:
                is_break = True

        # Проверяем занятость слота
        slot_occupied = False
        if not is_break:
            slot_end_time = current_time + timedelta(minutes=interval)

            if employee_id:
                # Конкретный мастер - проверяем его занятость
                for booking in existing_bookings:
                    if booking.employee_id != employee_id:
                        continue
                    booking_start = datetime.combine(selected_date_obj, booking.booking_time)
                    booking_duration = booking.service.duration_minutes if booking.service and booking.service.duration_minutes else 0
                    booking_end = booking_start + timedelta(minutes=booking_duration)

                    overlap_start = max(current_time, booking_start)
                    overlap_end = min(slot_end_time, booking_end)

                    if overlap_start < overlap_end:
                        overlap_minutes = (overlap_end - overlap_start).total_seconds() / 60
                        occupation_percent = (overlap_minutes / interval) * 100
                        if occupation_percent > 30:
                            slot_occupied = True
                            break
            else:
                # "Любой мастер" - проверяем есть ли хотя бы один свободный
                service_end_time = current_time + timedelta(minutes=service_duration)
                if service_end_time > end_datetime:
                    slot_occupied = True
                else:
                    has_free_master = False
                    for emp in available_employees:
                        master_busy = False
                        for booking in existing_bookings:
                            if booking.employee_id != emp.id:
                                continue
                            booking_start = datetime.combine(selected_date_obj, booking.booking_time)
                            booking_duration = booking.service.duration_minutes if booking.service and booking.service.duration_minutes else 0
                            booking_end = booking_start + timedelta(minutes=booking_duration)
                            if not (service_end_time <= booking_start or current_time >= booking_end):
                                master_busy = True
                                break
                        if not master_busy:
                            has_free_master = True
                            break
                    if not has_free_master:
                        slot_occupied = True

        if not is_break:
            if slot_occupied:
                occupied_times.append(current_time.strftime("%H:%M"))
            else:
                available_times.append(current_time.strftime("%H:%M"))

        current_time += timedelta(minutes=interval)

    if not available_times and not occupied_times:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад к выбору даты", callback_data="back_to_dates")

        await callback.message.edit_text(
            "😔 К сожалению, на эту дату нет свободного времени.\n\nВыберите другую дату 📅",
            reply_markup=builder.as_markup()
        )
        await state.set_state(BookingStates.choosing_date)
    else:
        await callback.message.edit_text(
            f"📅 Дата: {selected_date}\n\n🕐 Выберите удобное время:\n🔒 - занято",
            reply_markup=client_kb.get_times_keyboard(available_times, occupied_times)
        )
        await state.set_state(BookingStates.choosing_time)

    await callback.answer()


# ===== ОТМЕНА ЗАПИСИ =====

@router.callback_query(F.data.startswith("cancel_booking:"))
async def confirm_cancel_booking(callback: CallbackQuery):
    """Запрос подтверждения отмены записи (группы записей)"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        # Получаем информацию о записи
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)
        booking = None
        for b in user_bookings:
            if b.id == booking_id:
                booking = b
                break

        if not booking:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        if booking.status not in ['pending', 'confirmed']:
            await callback.answer("❌ Эту запись нельзя отменить", show_alert=True)
            return

        # Находим все связанные записи (группу/визит)
        booking_group = find_booking_group(user_bookings, booking)
        first_booking = booking_group[0]

        # Показываем подтверждение
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, отменить", callback_data=f"do_cancel_booking:{first_booking.id}", style="danger")
        builder.button(text="❌ Нет, оставить", callback_data="back_to_my_bookings")
        builder.adjust(1)

        text = f"⚠️ <b>Вы уверены, что хотите отменить запись?</b>\n\n"
        text += f"📅 <b>{format_date_with_weekday(first_booking.booking_date)} в {first_booking.booking_time.strftime('%H:%M')}</b>\n"
        text += f"🏢 {first_booking.business.name}\n"

        if len(booking_group) > 1:
            text += f"💼 Услуги ({len(booking_group)}):\n"
            for b in booking_group:
                text += f"   • {b.service.name}\n"
        else:
            text += f"💼 {first_booking.service.name}"

        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

    await callback.answer()


@router.callback_query(F.data.startswith("do_cancel_booking:"))
async def cancel_booking_by_client(callback: CallbackQuery):
    """Финальная отмена записи (группы записей) клиентом после подтверждения"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        # Проверяем, принадлежит ли запись этому пользователю
        from database.crud import get_user_bookings
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)
        booking = None
        for b in user_bookings:
            if b.id == booking_id:
                booking = b
                break

        if not booking:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        if booking.status not in ['pending', 'confirmed']:
            await callback.answer("❌ Эту запись нельзя отменить", show_alert=True)
            return

        # Находим все связанные записи (группу/визит)
        booking_group = find_booking_group(user_bookings, booking)
        first_booking = booking_group[0]

        # Отменяем все записи группы
        for b in booking_group:
            b.status = 'cancelled'
        await session.commit()

        # Уведомляем владельца об отмене (отправляем для первой записи)
        from bot.services.notifications import notify_owner_cancelled_booking
        await notify_owner_cancelled_booking(callback.bot, first_booking)

    # Создаем inline кнопки для навигации
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои записи", callback_data="back_to_my_bookings")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")
    builder.adjust(1)

    services_text = f" ({len(booking_group)} услуг)" if len(booking_group) > 1 else ""

    await callback.message.edit_text(
        f"✅ Запись{services_text} на {format_date_with_weekday(first_booking.booking_date)} в {first_booking.booking_time.strftime('%H:%M')} отменена.\n\n"
        f"🏢 {first_booking.business.name}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    await callback.answer("✅ Запись успешно отменена")


@router.callback_query(F.data == "back_to_my_bookings")
async def back_to_my_bookings_handler(callback: CallbackQuery):
    """Возврат к списку моих записей"""
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )
        bookings = await get_user_bookings(session, user.id)

    from datetime import datetime
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    now = datetime.now()
    active_bookings = []
    for b in bookings:
        if b.status in ["pending", "confirmed"]:
            booking_datetime = datetime.combine(b.booking_date, b.booking_time)
            if booking_datetime > now:
                active_bookings.append(b)

    if active_bookings:
        text, keyboard, _ = build_bookings_page(active_bookings, page=0)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")
        builder.adjust(1)
        await callback.message.edit_text(
            "📭 У вас нет активных записей.\n\nСамое время записаться! 😊",
            reply_markup=builder.as_markup()
        )

    await callback.answer()


# ===== ДЕТАЛИ ЗАПИСИ И ПЕРЕНОС =====

def find_booking_group(bookings: list, target_booking) -> list:
    """Находит группу связанных записей (один визит) для указанной записи."""
    # Фильтруем записи того же клиента, бизнеса и даты
    same_context = [
        b for b in bookings
        if b.business_id == target_booking.business_id
        and b.booking_date == target_booking.booking_date
        and b.status in ['pending', 'confirmed']
    ]

    if not same_context:
        return [target_booking]

    # Сортируем по времени
    same_context = sorted(same_context, key=lambda b: b.booking_time)

    # Группируем последовательные записи
    groups = []
    current_group = [same_context[0]]

    for i in range(1, len(same_context)):
        prev = same_context[i - 1]
        curr = same_context[i]

        prev_end = datetime.combine(prev.booking_date, prev.booking_time) + timedelta(minutes=prev.service.duration_minutes)
        curr_start = datetime.combine(curr.booking_date, curr.booking_time)

        # Допускаем погрешность в 5 минут
        if abs((curr_start - prev_end).total_seconds()) <= 300:
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]

    groups.append(current_group)

    # Находим группу, содержащую целевую запись
    for group in groups:
        if any(b.id == target_booking.id for b in group):
            return group

    return [target_booking]


@router.callback_query(F.data.startswith("booking_details:"))
async def show_booking_details(callback: CallbackQuery):
    """Показать детали записи (группы записей) с возможностью переноса или отмены"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)
        booking = None
        for b in user_bookings:
            if b.id == booking_id:
                booking = b
                break

        if not booking:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        if booking.status not in ['pending', 'confirmed']:
            await callback.answer("❌ Эта запись уже неактивна", show_alert=True)
            return

        # Находим все связанные записи (группу/визит)
        booking_group = find_booking_group(user_bookings, booking)
        first_booking = booking_group[0]

        # Формируем текст с деталями записи
        status_text = "⏳ Ожидает подтверждения" if first_booking.status == "pending" else "✅ Подтверждена"

        text = f"📋 <b>Детали записи</b>\n\n"
        text += f"📅 <b>Дата:</b> {format_date_with_weekday(first_booking.booking_date)}\n"
        text += f"🕐 <b>Время:</b> {first_booking.booking_time.strftime('%H:%M')}\n"
        text += f"📊 <b>Статус:</b> {status_text}\n\n"
        text += f"🏢 <b>Заведение:</b> {first_booking.business.name}\n"

        # Показываем все услуги визита
        total_price = 0
        total_duration = 0
        has_price = True
        if len(booking_group) > 1:
            text += f"💼 <b>Услуги ({len(booking_group)}):</b>\n"
            for b in booking_group:
                price = b.service.price or 0
                duration = b.service.duration_minutes or 0
                if b.service.price is not None:
                    text += f"   • {b.service.name} - {price} ₽"
                else:
                    text += f"   • {b.service.name}"
                    has_price = False
                if b.employee:
                    text += f" ({b.employee.name})"
                text += "\n"
                total_price += price
                total_duration += duration
            if has_price and total_price > 0:
                text += f"\n💰 <b>Общая стоимость:</b> {total_price} ₽\n"
            if total_duration > 0:
                text += f"⏱ <b>Общая длительность:</b> {total_duration} мин\n"
        else:
            text += f"💼 <b>Услуга:</b> {first_booking.service.name}\n"
            if first_booking.service.price is not None:
                text += f"💰 <b>Стоимость:</b> {first_booking.service.price} ₽\n"
            if first_booking.service.duration_minutes:
                text += f"⏱ <b>Длительность:</b> {first_booking.service.duration_minutes} мин\n"
            if first_booking.employee:
                text += f"👤 <b>Мастер:</b> {first_booking.employee.name}\n"

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        # Используем ID первой записи группы для переноса/отмены всей группы
        builder.button(text="🔄 Перенести запись", callback_data=f"reschedule_booking:{first_booking.id}", style="primary")
        builder.button(text="❌ Отменить запись", callback_data=f"cancel_booking:{first_booking.id}", style="danger")
        builder.button(text="◀️ Назад к записям", callback_data="back_to_my_bookings")
        builder.adjust(1)

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    await callback.answer()


@router.callback_query(F.data.startswith("reschedule_booking:"))
async def start_reschedule_booking(callback: CallbackQuery, state: FSMContext):
    """Начало процесса переноса записи (группы записей) - выбор новой даты"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)
        booking = None
        for b in user_bookings:
            if b.id == booking_id:
                booking = b
                break

        if not booking:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        if booking.status not in ['pending', 'confirmed']:
            await callback.answer("❌ Эту запись нельзя перенести", show_alert=True)
            return

        # Находим все связанные записи (группу/визит)
        booking_group = find_booking_group(user_bookings, booking)
        first_booking = booking_group[0]

        # Вычисляем общую длительность всех услуг
        total_duration = sum(b.service.duration_minutes for b in booking_group)

        # Собираем информацию о всех записях группы
        group_info = []
        for b in booking_group:
            group_info.append({
                'id': b.id,
                'service_id': b.service_id,
                'service_name': b.service.name,
                'duration': b.service.duration_minutes,
                'employee_id': b.employee_id
            })

        # Сохраняем данные для переноса
        await state.update_data(
            reschedule_booking_id=first_booking.id,
            reschedule_booking_ids=[b.id for b in booking_group],  # Все ID группы
            reschedule_group_info=group_info,  # Информация о всех записях
            reschedule_business_id=first_booking.business_id,
            reschedule_employee_id=first_booking.employee_id,
            reschedule_service_duration=total_duration,  # Общая длительность
            reschedule_old_date=first_booking.booking_date.strftime("%d.%m.%Y"),
            reschedule_old_time=first_booking.booking_time.strftime("%H:%M"),
            reschedule_services_count=len(booking_group)
        )

        # Получаем выходные мастера если он назначен
        exclude_dates_list = []
        if first_booking.employee_id:
            exclude_dates = await get_employee_days_off_dates(first_booking.employee_id, 60)
            exclude_dates_list = list(exclude_dates)

        today = date.today()

        services_text = f" ({len(booking_group)} услуг)" if len(booking_group) > 1 else ""

        await callback.message.edit_text(
            f"🔄 <b>Перенос записи{services_text}</b>\n\n"
            f"📅 Текущая дата: {format_date_with_weekday(first_booking.booking_date)} в {first_booking.booking_time.strftime('%H:%M')}\n\n"
            f"Выберите новую дату:",
            reply_markup=client_kb.get_booking_calendar_keyboard(
                today.year, today.month,
                exclude_dates=exclude_dates_list,
                callback_prefix="reschedule_date",
                back_callback="back_to_booking_details"
            ),
            parse_mode="HTML"
        )
        await state.set_state(BookingStates.reschedule_choosing_date)

    await callback.answer()


@router.callback_query(F.data == "back_to_booking_details")
async def back_to_booking_details(callback: CallbackQuery, state: FSMContext):
    """Возврат к деталям записи из процесса переноса"""
    data = await state.get_data()
    booking_id = data.get('reschedule_booking_id')

    if booking_id:
        await state.clear()
        # Имитируем нажатие на детали записи
        callback.data = f"booking_details:{booking_id}"
        await show_booking_details(callback)
    else:
        await state.clear()
        await back_to_my_bookings_handler(callback)


@router.callback_query(F.data.startswith("cal_nav:"), BookingStates.reschedule_choosing_date)
async def reschedule_calendar_navigation(callback: CallbackQuery, state: FSMContext):
    """Навигация по календарю при переносе записи"""
    parts = callback.data.split(":")
    year = int(parts[1])
    month = int(parts[2])

    data = await state.get_data()
    employee_id = data.get('reschedule_employee_id')

    # Получаем выходные мастера
    exclude_dates_list = []
    if employee_id:
        exclude_dates = await get_employee_days_off_dates(employee_id, 60)
        exclude_dates_list = list(exclude_dates)

    old_date = data.get('reschedule_old_date', '')
    old_time = data.get('reschedule_old_time', '')

    await callback.message.edit_text(
        f"🔄 <b>Перенос записи</b>\n\n"
        f"📅 Текущая дата: {old_date} в {old_time}\n\n"
        f"Выберите новую дату:",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            year, month,
            exclude_dates=exclude_dates_list,
            callback_prefix="reschedule_date",
            back_callback="back_to_booking_details"
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reschedule_date:"), BookingStates.reschedule_choosing_date)
async def reschedule_date_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора новой даты при переносе"""
    date_str = callback.data.split(":", 1)[1]
    selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    data = await state.get_data()
    await state.update_data(reschedule_new_date=date_str)

    business_id = data['reschedule_business_id']
    employee_id = data.get('reschedule_employee_id')
    service_duration = data.get('reschedule_service_duration', 60)
    booking_id = data['reschedule_booking_id']

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

        # Определяем шаг записи
        interval = business.booking_interval_minutes
        if employee_id:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            employee = result.scalar_one_or_none()
            if employee and employee.booking_interval_minutes:
                interval = employee.booking_interval_minutes

        # Время работы
        start_time = business.working_hours_start if business.working_hours_start else datetime.strptime("09:00", "%H:%M").time()
        end_time = business.working_hours_end if business.working_hours_end else datetime.strptime("18:00", "%H:%M").time()

        # Получаем существующие записи
        from sqlalchemy import and_
        if employee_id:
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    and_(
                        Booking.business_id == business_id,
                        Booking.employee_id == employee_id,
                        Booking.booking_date == selected_date,
                        Booking.status.in_(["pending", "confirmed"]),
                        Booking.id != booking_id  # Исключаем текущую запись
                    )
                )
            )
        else:
            result = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    and_(
                        Booking.business_id == business_id,
                        Booking.booking_date == selected_date,
                        Booking.status.in_(["pending", "confirmed"]),
                        Booking.id != booking_id
                    )
                )
            )
        existing_bookings = result.scalars().all()

    # Генерируем доступные слоты
    available_times = []
    occupied_times = []
    current_time = datetime.combine(selected_date, start_time)
    end_datetime = datetime.combine(selected_date, end_time)

    # Если сегодня, начинаем с текущего времени + 1 час
    if selected_date == datetime.now().date():
        now_plus_hour = datetime.now() + timedelta(hours=1)
        if current_time < now_plus_hour:
            current_time = now_plus_hour
            minutes = (current_time.minute // interval + 1) * interval
            if minutes >= 60:
                current_time = current_time.replace(minute=0) + timedelta(hours=1)
            else:
                current_time = current_time.replace(minute=minutes)

    while current_time + timedelta(minutes=service_duration) <= end_datetime:
        is_break = False
        if business.break_start and business.break_end:
            if business.break_start <= current_time.time() < business.break_end:
                is_break = True

        slot_occupied = False
        if not is_break and employee_id:
            for booking in existing_bookings:
                if booking.employee_id != employee_id:
                    continue
                booking_start = datetime.combine(selected_date, booking.booking_time)
                booking_end = booking_start + timedelta(minutes=booking.service.duration_minutes)

                service_end = current_time + timedelta(minutes=service_duration)
                if not (service_end <= booking_start or current_time >= booking_end):
                    slot_occupied = True
                    break

        if not is_break:
            if slot_occupied:
                occupied_times.append(current_time.strftime("%H:%M"))
            else:
                available_times.append(current_time.strftime("%H:%M"))

        current_time += timedelta(minutes=interval)

    old_date = data.get('reschedule_old_date', '')
    old_time = data.get('reschedule_old_time', '')

    await callback.message.edit_text(
        f"🔄 <b>Перенос записи</b>\n\n"
        f"📅 Было: {old_date} в {old_time}\n"
        f"📅 Новая дата: {date_str}\n\n"
        f"🕐 Выберите новое время:\n🔒 - занято",
        reply_markup=client_kb.get_reschedule_times_keyboard(available_times, occupied_times),
        parse_mode="HTML"
    )
    await state.set_state(BookingStates.reschedule_choosing_time)
    await callback.answer()


@router.callback_query(F.data.startswith("reschedule_time_occupied:"), BookingStates.reschedule_choosing_time)
async def reschedule_occupied_time_clicked(callback: CallbackQuery):
    """Клик на занятый слот при переносе"""
    await callback.answer("🔒 Это время уже занято. Выберите другое.", show_alert=True)


@router.callback_query(F.data.startswith("reschedule_time:"), BookingStates.reschedule_choosing_time)
async def reschedule_time_chosen(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора нового времени - показ подтверждения"""
    time_str = callback.data.split(":")[1] + ":" + callback.data.split(":")[2]

    data = await state.get_data()
    await state.update_data(reschedule_new_time=time_str)

    old_date = data.get('reschedule_old_date', '')
    old_time = data.get('reschedule_old_time', '')
    new_date = data.get('reschedule_new_date', '')

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить перенос", callback_data="confirm_reschedule", style="success")
    builder.button(text="🔄 Выбрать другое время", callback_data="reschedule_back_to_times")
    builder.button(text="❌ Отменить перенос", callback_data="cancel_reschedule", style="danger")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🔄 <b>Подтверждение переноса</b>\n\n"
        f"📅 <b>Было:</b> {old_date} в {old_time}\n"
        f"📅 <b>Станет:</b> {new_date} в {time_str}\n\n"
        f"Подтвердить перенос записи?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "reschedule_back_to_times")
async def reschedule_back_to_times(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору времени при переносе"""
    data = await state.get_data()
    new_date_str = data.get('reschedule_new_date')

    # Имитируем выбор даты заново
    callback.data = f"reschedule_date:{new_date_str}"
    await state.set_state(BookingStates.reschedule_choosing_date)
    await reschedule_date_chosen(callback, state)


@router.callback_query(F.data == "confirm_reschedule")
async def confirm_reschedule(callback: CallbackQuery, state: FSMContext):
    """Подтверждение переноса записи (группы записей)"""
    data = await state.get_data()

    booking_ids = data.get('reschedule_booking_ids', [data['reschedule_booking_id']])
    new_date_str = data['reschedule_new_date']
    new_time_str = data['reschedule_new_time']

    new_date = datetime.strptime(new_date_str, "%d.%m.%Y").date()
    new_base_time = datetime.strptime(new_time_str, "%H:%M").time()

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)

        # Находим все записи группы
        bookings_to_update = []
        for b in user_bookings:
            if b.id in booking_ids:
                bookings_to_update.append(b)

        if not bookings_to_update:
            await callback.answer("❌ Записи не найдены", show_alert=True)
            await state.clear()
            return

        # Сортируем по времени для правильного порядка
        bookings_to_update = sorted(bookings_to_update, key=lambda b: b.booking_time)

        first_booking = bookings_to_update[0]
        old_date = first_booking.booking_date
        old_time = first_booking.booking_time

        # Проверяем статусы
        for booking in bookings_to_update:
            if booking.status not in ['pending', 'confirmed']:
                await callback.answer("❌ Некоторые записи уже нельзя перенести", show_alert=True)
                await state.clear()
                return

        # Обновляем все записи группы с последовательным временем
        current_time = datetime.combine(new_date, new_base_time)
        for booking in bookings_to_update:
            booking.booking_date = new_date
            booking.booking_time = current_time.time()
            # Следующая услуга начинается после окончания этой
            current_time += timedelta(minutes=booking.service.duration_minutes)

        await session.commit()

        # Уведомляем владельца/мастера о переносе (отправляем для первой записи)
        from bot.services.notifications import notify_owner_rescheduled_booking
        await notify_owner_rescheduled_booking(callback.bot, first_booking, old_date, old_time)

    await state.clear()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои записи", callback_data="back_to_my_bookings")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")
    builder.adjust(1)

    services_text = f" ({len(bookings_to_update)} услуг)" if len(bookings_to_update) > 1 else ""

    await callback.message.edit_text(
        f"✅ <b>Запись{services_text} успешно перенесена!</b>\n\n"
        f"📅 Было: {format_date_with_weekday(old_date)} в {old_time.strftime('%H:%M')}\n"
        f"📅 Стало: {format_date_with_weekday(new_date)} в {new_base_time.strftime('%H:%M')}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer("✅ Запись перенесена!")


@router.callback_query(F.data == "reschedule_back_to_calendar")
async def reschedule_back_to_calendar(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору даты при переносе"""
    data = await state.get_data()
    employee_id = data.get('reschedule_employee_id')

    # Получаем выходные мастера
    exclude_dates_list = []
    if employee_id:
        exclude_dates = await get_employee_days_off_dates(employee_id, 60)
        exclude_dates_list = list(exclude_dates)

    old_date = data.get('reschedule_old_date', '')
    old_time = data.get('reschedule_old_time', '')

    from datetime import date
    today = date.today()

    await callback.message.edit_text(
        f"🔄 <b>Перенос записи</b>\n\n"
        f"📅 Текущая дата: {old_date} в {old_time}\n\n"
        f"Выберите новую дату:",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            today.year, today.month,
            exclude_dates=exclude_dates_list,
            callback_prefix="reschedule_date",
            back_callback="back_to_booking_details"
        ),
        parse_mode="HTML"
    )
    await state.set_state(BookingStates.reschedule_choosing_date)
    await callback.answer()


@router.callback_query(F.data == "cancel_reschedule")
async def cancel_reschedule(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса переноса"""
    data = await state.get_data()
    booking_id = data.get('reschedule_booking_id')
    await state.clear()

    if booking_id:
        callback.data = f"booking_details:{booking_id}"
        await show_booking_details(callback)
    else:
        await back_to_my_bookings_handler(callback)


# ===== ПРОСМОТР ИНФОРМАЦИИ О БИЗНЕСЕ ИЗ ЗАПИСЕЙ =====

@router.callback_query(F.data.startswith("booking_business_info:"))
async def show_booking_business_info(callback: CallbackQuery):
    """Показать информацию о бизнесе из записей"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business:
        await callback.answer("Бизнес не найден", show_alert=True)
        return

    import json
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    # Формируем информацию о бизнесе
    info_text = f"ℹ️ <b>Информация о заведении</b>\n\n"
    info_text += f"🏢 <b>{business.name}</b>\n\n"

    if business.description:
        info_text += f"📝 {business.description}\n\n"

    # Добавляем контактную информацию
    if business.phone:
        formatted_phone = format_phone(business.phone)
        info_text += f'📞 Телефон: {formatted_phone}\n'

    if business.address:
        from urllib.parse import quote
        encoded_address = quote(business.address)
        yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
        gis_url = f"https://2gis.ru/search/{encoded_address}"
        info_text += f'📍 Адрес: <a href="{yandex_maps_url}">{business.address}</a>\n'
        info_text += f'\n🗺 <a href="{yandex_maps_url}">Открыть в Яндекс.Картах</a> | '
        info_text += f'<a href="{gis_url}">2ГИС</a>\n'

    # Рабочие часы
    if business.working_hours_start and business.working_hours_end:
        info_text += f"\n⏰ Часы работы: {business.working_hours_start.strftime('%H:%M')} - {business.working_hours_end.strftime('%H:%M')}\n"

    # Время перерыва
    if business.break_start and business.break_end:
        info_text += f"☕ Перерыв: {business.break_start.strftime('%H:%M')} - {business.break_end.strftime('%H:%M')}\n"

    # Создаем кнопки для фото и инструкций
    builder = InlineKeyboardBuilder()

    has_photos = False
    if business.photos:
        try:
            photos_data = json.loads(business.photos)
            has_photos = len(photos_data) > 0
        except:
            pass

    has_directions = business.directions is not None and business.directions.strip() != ""

    if has_photos:
        builder.button(text="📷 Посмотреть фото", callback_data=f"view_photos:{business_id}")
    if has_directions:
        builder.button(text="🗺 Как добраться", callback_data=f"view_directions:{business_id}")

    builder.button(text="◀️ Назад к записям", callback_data="back_to_bookings")
    builder.adjust(1)

    # Удаляем предыдущее сообщение и отправляем новое
    try:
        await callback.message.delete()
    except:
        pass

    await callback.bot.send_message(
        chat_id=callback.from_user.id,
        text=info_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_bookings")
async def back_to_bookings_handler(callback: CallbackQuery):
    """Возврат к списку записей"""
    # Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except:
        pass

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        bookings = await get_user_bookings(session, user.id)

    # Получаем роли пользователя для кнопок переключения
    show_admin, show_master = await get_user_roles(callback.from_user.id)

    # Показываем Reply клавиатуру с основным меню клиента
    reply_keyboard = client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)

    if not bookings:
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text="📭 У вас пока нет записей.\n\nНажмите «📅 Записаться», чтобы создать первую! 😊",
            reply_markup=reply_keyboard
        )
        await callback.answer()
        return

    # Группируем записи по статусу и времени
    from datetime import datetime
    now = datetime.now()

    active_bookings = []
    for b in bookings:
        if b.status in ["pending", "confirmed"]:
            # Создаём datetime из даты и времени записи
            booking_datetime = datetime.combine(b.booking_date, b.booking_time)
            # Добавляем только будущие записи
            if booking_datetime > now:
                active_bookings.append(b)

    if active_bookings:
        text = "📅 <b>Активные записи:</b>\n\n"
        for booking in active_bookings:
            status_emoji = "⏳" if booking.status == "pending" else "✅"
            text += f"{status_emoji} <b>{format_date_with_weekday(booking.booking_date)} в {booking.booking_time.strftime('%H:%M')}</b>\n"
            text += f"🏢 {booking.business.name}\n"
            text += f"💼 {booking.service.name}\n"
            if booking.employee:
                text += f"👤 {booking.employee.name}\n"
            text += "\n"

        # Добавляем inline кнопки
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        import json
        builder = InlineKeyboardBuilder()

        # Группируем записи по бизнесам для кнопок просмотра информации
        businesses_with_bookings = {}
        for booking in active_bookings:
            if booking.business_id not in businesses_with_bookings:
                businesses_with_bookings[booking.business_id] = booking.business

        # Добавляем кнопки для просмотра информации о каждом бизнесе
        for business_id, business in businesses_with_bookings.items():
            # Проверяем наличие фото и инструкций
            has_photos = False
            has_directions = False
            has_contacts = business.phone or business.address

            if business.photos:
                try:
                    photos_data = json.loads(business.photos)
                    has_photos = len(photos_data) > 0
                except:
                    pass

            has_directions = business.directions is not None and business.directions.strip() != ""

            # Создаем кнопки для этого бизнеса
            if has_photos or has_directions or has_contacts:
                builder.button(
                    text=f"ℹ️ Информация: {business.name}",
                    callback_data=f"booking_business_info:{business_id}"
                )

        # Добавляем кнопки отмены для каждой записи
        for booking in active_bookings:
            btn_text = f"❌ Отменить запись от {format_date_with_weekday(booking.booking_date, short=True)}"
            builder.button(text=btn_text, callback_data=f"cancel_booking:{booking.id}", style="danger")

        # Добавляем кнопку "Назад"
        builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")

        builder.adjust(1)

        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text="У вас нет активных записей.",
            reply_markup=reply_keyboard
        )

    await callback.answer()


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_handler(callback: CallbackQuery):
    """Возврат в главное меню"""
    # Удаляем предыдущее сообщение сначала
    try:
        await callback.message.delete()
    except:
        pass

    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )
        businesses = await get_user_businesses(session, user.id)
        employee = await get_employee_by_telegram_id(session, callback.from_user.id)

    is_admin = callback.from_user.id in ADMIN_IDS
    mlm_owner = await can_be_business_owner(callback.from_user.id)
    show_admin = is_admin or len(businesses) > 0 or mlm_owner
    show_master = employee is not None

    await callback.bot.send_message(
        chat_id=callback.from_user.id,
        text="🏠 Главное меню",
        reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
    )
    await callback.answer()


# ===== ПРОСМОТР ФОТО И ИНСТРУКЦИЙ =====

@router.callback_query(F.data.startswith("view_photos:"))
async def view_business_photos(callback: CallbackQuery):
    """Просмотр фотографий бизнеса"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business or not business.photos:
        await callback.answer("Фотографии не найдены", show_alert=True)
        return

    import json
    from aiogram.types import InputMediaPhoto
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    try:
        photos_data = json.loads(business.photos)
        if not photos_data:
            await callback.answer("Фотографии не найдены", show_alert=True)
            return

        # Отправляем фотографии группой (медиагруппа)
        media_group = []
        for i, photo_id in enumerate(photos_data[:10]):  # Максимум 10 фото
            if i == 0:
                media_group.append(InputMediaPhoto(
                    media=photo_id,
                    caption=f"📷 Фотографии: {business.name}"
                ))
            else:
                media_group.append(InputMediaPhoto(media=photo_id))

        await callback.message.answer_media_group(media_group)

        # Добавляем кнопки навигации
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад к информации", callback_data=f"booking_business_info:{business_id}")
        builder.button(text="📋 К моим записям", callback_data="back_to_bookings")
        builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")
        builder.adjust(1)

        await callback.message.answer("Навигация:", reply_markup=builder.as_markup())
        await callback.answer("✅ Фотографии отправлены")

    except Exception as e:
        await callback.answer("Ошибка при загрузке фотографий", show_alert=True)


@router.callback_query(F.data.startswith("view_directions:"))
async def view_business_directions(callback: CallbackQuery):
    """Просмотр инструкции как добраться"""
    business_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        business = await get_business_by_id(session, business_id)

    if not business or not business.directions:
        await callback.answer("Инструкция не найдена", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    # Формируем кликабельный адрес
    address_text = ""
    if business.address:
        from urllib.parse import quote
        encoded_address = quote(business.address)
        yandex_maps_url = f"https://yandex.ru/maps/?text={encoded_address}"
        gis_url = f"https://2gis.ru/search/{encoded_address}"
        address_text = f'\n\n📍 <b>Адрес:</b> <a href="{yandex_maps_url}">{business.address}</a>\n\n' \
                      f'🗺 <a href="{yandex_maps_url}">Открыть в Яндекс.Картах</a> | ' \
                      f'<a href="{gis_url}">2ГИС</a>'

    directions_text = f"""
🗺 <b>Как добраться</b>

{business.directions}
{address_text}
"""

    # Добавляем кнопки навигации
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад к информации", callback_data=f"booking_business_info:{business_id}")
    builder.button(text="📋 К моим записям", callback_data="back_to_bookings")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")
    builder.adjust(1)

    await callback.message.answer(
        directions_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=builder.as_markup()
    )
    await callback.answer("✅ Инструкция отправлена")


# ===== БЫСТРАЯ ПОВТОРНАЯ ЗАПИСЬ =====

@router.message(F.text == "🔄 Повторить запись")
async def quick_rebooking(message: Message, state: FSMContext):
    """Быстрая повторная запись на основе истории"""
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )

        # Получаем последние 5 завершенных записей
        bookings = await get_user_bookings(session, user.id)
        completed_bookings = [b for b in bookings if b.status == "completed"][:5]

    # Получаем роли пользователя для кнопок переключения
    show_admin, show_master = await get_user_roles(message.from_user.id)
    reply_keyboard = client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)

    if not completed_bookings:
        await message.answer(
            "У вас пока нет завершенных записей.\n"
            "Используйте '📅 Записаться' для первой записи.",
            reply_markup=reply_keyboard
        )
        return

    # Создаем кнопки для каждой записи
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    for booking in completed_bookings:
        btn_text = f"{booking.business.name} - {booking.service.name}"
        if booking.employee:
            btn_text += f" ({booking.employee.name})"

        builder.button(
            text=btn_text,
            callback_data=f"repeat_booking:{booking.id}"
        )

    # Добавляем кнопку возврата в главное меню
    builder.button(text="🏠 Главное меню", callback_data="back_to_main_menu")

    builder.adjust(1)

    await message.answer(
        "📍 Кнопки переключения режимов внизу ⬇️",
        reply_markup=reply_keyboard
    )
    await message.answer(
        "🔄 <b>Повторить запись</b>\n\n"
        "Выберите услугу из ваших прошлых записей: 👇",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("repeat_booking:"))
async def process_repeat_booking(callback: CallbackQuery, state: FSMContext):
    """Обработка повторной записи"""
    old_booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        # Получаем старую запись
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name
        )

        user_bookings = await get_user_bookings(session, user.id)
        old_booking = None
        for b in user_bookings:
            if b.id == old_booking_id:
                old_booking = b
                break

        if not old_booking:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return

        # Сохраняем данные из старой записи
        await state.update_data(
            business_id=old_booking.business_id,
            business_name=old_booking.business.name,
            service_id=old_booking.service_id,
            service_name=old_booking.service.name,
            service_duration=old_booking.service.duration_minutes,
            service_price=old_booking.service.price,
            employee_id=old_booking.employee_id,
            employee_name=old_booking.employee.name if old_booking.employee else "Любой мастер"
        )

    # Получаем выходные дни мастера (если выбран конкретный мастер)
    exclude_dates = []
    if old_booking.employee_id:
        exclude_dates = await get_employee_days_off_dates(old_booking.employee_id, 60)

    employee_name = old_booking.employee.name if old_booking.employee else "Любой мастер"

    # Показываем календарь
    today = date.today()
    await callback.message.edit_text(
        f"🔄 <b>Повторная запись</b>\n\n"
        f"🏢 {old_booking.business.name}\n"
        f"💼 {old_booking.service.name}\n"
        f"👤 {employee_name}\n\n"
        f"📅 Выберите дату:\n"
        f"<i>· — прошедшие дни, ✕ — выходной мастера</i>",
        parse_mode="HTML",
        reply_markup=client_kb.get_booking_calendar_keyboard(
            today.year, today.month,
            exclude_dates=exclude_dates,
            callback_prefix="date",
            back_callback="client_main_menu"
        )
    )
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()


# ===== ВОЗВРАТ В ГЛАВНОЕ МЕНЮ =====

@router.callback_query(F.data == "client_main_menu")
async def back_to_client_main_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню клиента"""
    await state.clear()

    # Проверяем роли пользователя
    from database import get_or_create_user, get_user_businesses, get_employee_by_telegram_id
    async with async_session_maker() as session:
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name
        )
        businesses = await get_user_businesses(session, user.id)
        employee = await get_employee_by_telegram_id(session, callback.from_user.id)

    is_admin = callback.from_user.id in ADMIN_IDS
    mlm_owner = await can_be_business_owner(callback.from_user.id)
    show_admin = is_admin or len(businesses) > 0 or mlm_owner
    show_master = employee is not None

    # Удаляем сообщение с выбором бизнеса
    try:
        await callback.message.delete()
    except:
        pass

    # Отправляем новое сообщение с главным меню
    await callback.bot.send_message(
        chat_id=callback.from_user.id,
        text="🏠 Добро пожаловать! 😊\n\nВыберите действие в меню ниже ⬇️",
        reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
    )
    await callback.answer()


# ===== ОБРАБОТКА ПРЕДОПЛАТЫ =====


async def _build_prepayment_owner_text(booking: Booking, session, receipt_note: str = None) -> str:
    """Формирует подробное уведомление о предоплате для владельца"""
    from bot.utils.business_types import is_venue_rental_type, get_terminology
    from bot.utils.validators import format_phone as fmt_phone

    business = booking.business
    client = booking.client

    # Ищем все связанные бронирования этого визита (одна запись на услугу)
    stmt = select(Booking).options(
        selectinload(Booking.service),
        selectinload(Booking.employee)
    ).where(
        Booking.client_id == booking.client_id,
        Booking.business_id == booking.business_id,
        Booking.booking_date == booking.booking_date,
        Booking.booking_time == booking.booking_time,
        Booking.status.in_(["pending_prepayment", "prepayment_sent"])
    )
    result = await session.execute(stmt)
    related_bookings = list(result.scalars().all())

    if not related_bookings:
        related_bookings = [booking]

    is_venue = is_venue_rental_type(business.business_type)
    term = get_terminology(business.business_type)
    emp_label = term.get("employee", "Мастер")

    # Ссылка на профиль клиента
    client_link = f'<a href="tg://user?id={client.telegram_id}">{client.full_name}</a>'

    owner_text = (
        f"💳 <b>Клиент отправил предоплату!</b>\n\n"
        f"🏢 {business.name}\n"
        f"📅 {booking.booking_date.strftime('%d.%m.%Y')} в {booking.booking_time.strftime('%H:%M')}\n\n"
        f"👤 Клиент: {client_link}\n"
    )

    if client.phone:
        formatted_phone = fmt_phone(client.phone)
        tel_link = formatted_phone if formatted_phone.startswith('+') else '+7' + formatted_phone[1:]
        owner_text += f'📱 Телефон: <a href="tel:{tel_link}">{formatted_phone}</a>\n'

    # Собираем услуги: основные и дополнительные
    main_services = []
    additional_services = []
    total_price = 0
    total_duration = 0
    employee_info = None

    for bk in related_bookings:
        if bk.service:
            svc = bk.service
            if svc.is_additional:
                additional_services.append(svc)
            else:
                main_services.append(svc)
            total_price += svc.price or 0
            total_duration += svc.duration_minutes or 0
        if bk.employee and not employee_info:
            employee_info = bk.employee

    all_services = main_services + additional_services
    if len(all_services) > 1:
        owner_text += "\n💼 Услуги:\n"
        for svc in main_services:
            price_str = f" - {svc.price}₽" if svc.price else ""
            owner_text += f"  • {svc.name} ({svc.duration_minutes} мин{price_str})\n"
        if additional_services:
            owner_text += "\n  📎 Доп. услуги:\n"
            for svc in additional_services:
                price_str = f" - {svc.price}₽" if svc.price else ""
                owner_text += f"  • {svc.name} ({svc.duration_minutes} мин{price_str})\n"

        owner_text += f"\n⏱ Общая длительность: {total_duration} мин\n"
        if total_price > 0:
            owner_text += f"💰 Общая сумма: {total_price}₽\n"
    else:
        svc = booking.service
        owner_text += f"\n💼 Услуга: {svc.name} ({svc.duration_minutes} мин)\n"
        if svc.price:
            total_price = svc.price
            owner_text += f"💰 Сумма: {svc.price}₽\n"

    # Мастер/зал
    emp = employee_info or booking.employee
    if emp:
        if is_venue:
            owner_text += f"\n🏠 Помещение: {emp.name}\n"
        else:
            owner_text += f"\n👔 {emp_label}: {emp.name}\n"

    # Предоплата с процентом
    prepayment_amount = booking.prepayment_amount
    prepayment_percent = business.prepayment_percent or 100
    owner_text += f"\n💰 <b>Сумма предоплаты: {prepayment_amount}₽</b>"
    if prepayment_percent < 100 and total_price > 0:
        owner_text += f" ({prepayment_percent}% от {total_price}₽)"
    owner_text += "\n"

    # Комментарий
    if booking.notes:
        owner_text += f"\n💬 Комментарий: {booking.notes}\n"

    if receipt_note:
        owner_text += f"\n{receipt_note}\n"

    owner_text += "\nПроверьте получение оплаты и подтвердите или отклоните."

    return owner_text

@router.callback_query(F.data.startswith("prepay_sent:"))
async def prepayment_sent_by_client(callback: CallbackQuery, state: FSMContext):
    """Клиент подтвердил отправку предоплаты"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        # Получаем бронирование со всеми связями
        stmt = select(Booking).options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.business).selectinload(Business.owner),
            selectinload(Booking.employee)
        ).where(Booking.id == booking_id)
        result = await session.execute(stmt)
        booking = result.scalar_one_or_none()

        if not booking:
            await callback.answer("Бронирование не найдено", show_alert=True)
            return

        if booking.status not in ("pending_prepayment", "prepayment_sent"):
            await callback.answer("Статус бронирования уже изменён", show_alert=True)
            return

        # Обновляем статус
        booking.status = "prepayment_sent"
        await session.commit()

        # Формируем подробное сообщение для владельца
        owner_text = await _build_prepayment_owner_text(booking, session)

        # Отправляем уведомление владельцу
        from bot.keyboards.admin_kb import get_booking_admin_actions_keyboard

        try:
            await callback.bot.send_message(
                chat_id=booking.business.owner.telegram_id,
                text=owner_text,
                parse_mode="HTML",
                reply_markup=get_booking_admin_actions_keyboard(booking_id, show_prepayment_confirm=True)
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления владельцу: {e}")

    # Обновляем сообщение клиента
    await callback.message.edit_text(
        f"✅ <b>Информация об оплате отправлена!</b>\n\n"
        f"Ожидайте подтверждения от владельца.\n"
        f"Вы получите уведомление, когда бронирование будет подтверждено.\n\n"
        f"💰 Сумма предоплаты: {booking.prepayment_amount}₽",
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer("Информация отправлена!")


@router.callback_query(F.data.startswith("cancel_prepay_booking:"))
async def cancel_prepayment_booking(callback: CallbackQuery, state: FSMContext):
    """Клиент отменяет бронирование с предоплатой"""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        # Получаем бронирование
        stmt = select(Booking).options(
            selectinload(Booking.business).selectinload(Business.owner),
            selectinload(Booking.service),
            selectinload(Booking.client)
        ).where(Booking.id == booking_id)
        result = await session.execute(stmt)
        booking = result.scalar_one_or_none()

        if not booking:
            await callback.answer("Бронирование не найдено", show_alert=True)
            return

        # Отменяем бронирование
        booking.status = "cancelled"
        await session.commit()

        # Уведомляем владельца
        try:
            await callback.bot.send_message(
                chat_id=booking.business.owner.telegram_id,
                text=(
                    f"❌ <b>Клиент отменил бронирование</b>\n\n"
                    f"🏢 {booking.business.name}\n"
                    f"👤 {booking.client.full_name}\n"
                    f"📋 {booking.service.name}\n"
                    f"📅 {booking.booking_date.strftime('%d.%m.%Y')} в {booking.booking_time.strftime('%H:%M')}\n\n"
                    f"Предоплата не была подтверждена."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

    await callback.message.edit_text(
        "❌ Бронирование отменено.\n\n"
        "Если вы уже отправили предоплату, свяжитесь с владельцем для возврата.",
        parse_mode="HTML"
    )

    show_admin, show_master = await get_user_roles(callback.from_user.id)
    await callback.message.answer(
        "😊 Что хотите сделать?",
        reply_markup=client_kb.get_main_menu_keyboard(show_owner_button=show_admin, show_employee_button=show_master)
    )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("prepay_attach_receipt:"))
async def prepay_attach_receipt_handler(callback: CallbackQuery, state: FSMContext):
    """Клиент хочет прикрепить чек"""
    booking_id = int(callback.data.split(":")[1])

    # Сохраняем ID бронирования для последующей обработки
    await state.update_data(prepay_booking_id=booking_id)
    await state.set_state(BookingStates.uploading_receipt)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить (без чека)", callback_data=f"prepay_sent:{booking_id}")
    builder.button(text="❌ Отменить", callback_data=f"cancel_prepay_booking:{booking_id}", style="danger")
    builder.adjust(1)

    await callback.message.edit_text(
        "📸 <b>Отправьте фото или скриншот чека об оплате</b>\n\n"
        "Это поможет владельцу быстрее проверить и подтвердить вашу оплату.\n\n"
        "<i>Отправьте изображение чека или нажмите 'Пропустить'</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.message(BookingStates.uploading_receipt, F.photo)
async def receipt_photo_received(message: Message, state: FSMContext):
    """Получено фото чека от клиента"""
    data = await state.get_data()
    booking_id = data.get("prepay_booking_id")

    if not booking_id:
        await message.answer("Ошибка: бронирование не найдено. Попробуйте ещё раз.")
        await state.clear()
        return

    # Получаем file_id самой большой версии фото
    photo_file_id = message.photo[-1].file_id

    async with async_session_maker() as session:
        # Получаем бронирование со всеми связями
        stmt = select(Booking).options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.business).selectinload(Business.owner),
            selectinload(Booking.employee)
        ).where(Booking.id == booking_id)
        result = await session.execute(stmt)
        booking = result.scalar_one_or_none()

        if not booking:
            await message.answer("Бронирование не найдено")
            await state.clear()
            return

        if booking.status not in ("pending_prepayment", "prepayment_sent"):
            await message.answer("Статус бронирования уже изменён")
            await state.clear()
            return

        # Обновляем статус
        booking.status = "prepayment_sent"
        await session.commit()

        # Формируем подробное сообщение для владельца
        owner_text = await _build_prepayment_owner_text(
            booking, session,
            receipt_note="📸 <b>Клиент прикрепил чек (см. фото выше)</b>"
        )

        # Отправляем фото чека и уведомление владельцу
        from bot.keyboards.admin_kb import get_booking_admin_actions_keyboard

        try:
            # Сначала отправляем фото
            await message.bot.send_photo(
                chat_id=booking.business.owner.telegram_id,
                photo=photo_file_id,
                caption="📸 Чек от клиента"
            )
            # Затем сообщение с кнопками
            await message.bot.send_message(
                chat_id=booking.business.owner.telegram_id,
                text=owner_text,
                parse_mode="HTML",
                reply_markup=get_booking_admin_actions_keyboard(booking_id, show_prepayment_confirm=True)
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления владельцу: {e}")

    # Отвечаем клиенту
    await message.answer(
        f"✅ <b>Чек и информация об оплате отправлены!</b>\n\n"
        f"Ожидайте подтверждения от владельца.\n"
        f"Вы получите уведомление, когда бронирование будет подтверждено.\n\n"
        f"💰 Сумма предоплаты: {booking.prepayment_amount}₽",
        parse_mode="HTML"
    )

    await state.clear()


@router.message(BookingStates.uploading_receipt, F.document)
async def receipt_document_received(message: Message, state: FSMContext):
    """Получен документ (файл) чека от клиента"""
    data = await state.get_data()
    booking_id = data.get("prepay_booking_id")

    if not booking_id:
        await message.answer("Ошибка: бронирование не найдено. Попробуйте ещё раз.")
        await state.clear()
        return

    document_file_id = message.document.file_id

    async with async_session_maker() as session:
        stmt = select(Booking).options(
            selectinload(Booking.client),
            selectinload(Booking.service),
            selectinload(Booking.business).selectinload(Business.owner),
            selectinload(Booking.employee)
        ).where(Booking.id == booking_id)
        result = await session.execute(stmt)
        booking = result.scalar_one_or_none()

        if not booking:
            await message.answer("Бронирование не найдено")
            await state.clear()
            return

        if booking.status not in ("pending_prepayment", "prepayment_sent"):
            await message.answer("Статус бронирования уже изменён")
            await state.clear()
            return

        booking.status = "prepayment_sent"
        await session.commit()

        # Формируем подробное сообщение для владельца
        owner_text = await _build_prepayment_owner_text(
            booking, session,
            receipt_note="📎 <b>Клиент прикрепил документ (см. файл выше)</b>"
        )

        from bot.keyboards.admin_kb import get_booking_admin_actions_keyboard

        try:
            await message.bot.send_document(
                chat_id=booking.business.owner.telegram_id,
                document=document_file_id,
                caption="📎 Документ от клиента"
            )
            await message.bot.send_message(
                chat_id=booking.business.owner.telegram_id,
                text=owner_text,
                parse_mode="HTML",
                reply_markup=get_booking_admin_actions_keyboard(booking_id, show_prepayment_confirm=True)
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления владельцу: {e}")

    await message.answer(
        f"✅ <b>Документ и информация об оплате отправлены!</b>\n\n"
        f"Ожидайте подтверждения от владельца.\n"
        f"Вы получите уведомление, когда бронирование будет подтверждено.\n\n"
        f"💰 Сумма предоплаты: {booking.prepayment_amount}₽",
        parse_mode="HTML"
    )

    await state.clear()


@router.message(BookingStates.uploading_receipt)
async def receipt_wrong_format(message: Message, state: FSMContext):
    """Клиент отправил что-то кроме фото/документа"""
    data = await state.get_data()
    booking_id = data.get("prepay_booking_id")

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить (без чека)", callback_data=f"prepay_sent:{booking_id}")
    builder.button(text="❌ Отменить", callback_data=f"cancel_prepay_booking:{booking_id}", style="danger")
    builder.adjust(1)

    await message.answer(
        "❌ Пожалуйста, отправьте <b>фото</b> или <b>файл</b> чека.\n\n"
        "Или нажмите кнопку ниже, чтобы продолжить без чека.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

