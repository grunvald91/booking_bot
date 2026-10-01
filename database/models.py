"""
Модели базы данных для системы записи
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Boolean, Integer, Text, Time, Date, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


class User(Base):
    """Пользователи бота (клиенты и владельцы бизнеса)"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # === SUBSCRIPTION / TARIFF FIELDS ===
    # Тариф пользователя: standard (1 бизнес), business (3 бизнеса), network (безлимит)
    tariff: Mapped[str] = mapped_column(String(20), default="standard")
    # Максимум бизнесов по тарифу (0 = безлимит)
    max_businesses: Mapped[int] = mapped_column(Integer, default=1)
    # Статус подписки: trial, active, suspended, none
    subscription_status: Mapped[str] = mapped_column(String(20), default="none")
    # Дата окончания подписки/триала
    subscription_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Добавлен администратором вручную - без ограничений!
    is_manual_owner: Mapped[bool] = mapped_column(Boolean, default=False)

    # Связь с бизнесами (если пользователь - владелец)
    businesses: Mapped[List["Business"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    # Связь с записями
    bookings: Mapped[List["Booking"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    # Связь с абонементами клиента
    client_subscriptions: Mapped[List["ClientSubscription"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class Business(Base):
    """Бизнесы (салон красоты, автосервис и т.д.)"""
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_type: Mapped[str] = mapped_column(String(100))  # salon, auto_service, psychologist и т.д.
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    working_hours_start: Mapped[Optional[datetime.time]] = mapped_column(Time, nullable=True)
    working_hours_end: Mapped[Optional[datetime.time]] = mapped_column(Time, nullable=True)
    break_start: Mapped[Optional[datetime.time]] = mapped_column(Time, nullable=True)  # Начало перерыва
    break_end: Mapped[Optional[datetime.time]] = mapped_column(Time, nullable=True)  # Конец перерыва
    booking_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)  # Шаг записи по умолчанию
    photos: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON массив file_id фотографий
    video: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Telegram file_id видеообзора
    directions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Как добраться

    # Настройки предоплаты
    prepayment_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Включена ли предоплата
    prepayment_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Процент предоплаты (100 = полная)
    payment_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # Номер для перевода
    payment_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Дополнительные реквизиты (карта, СБП и т.д.)
    cancellation_policy_photo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Telegram file_id фото условий отмены
    cancellation_policy_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Текст условий отмены
    require_receipt_for_prepayment: Mapped[bool] = mapped_column(Boolean, default=False)  # Требовать чек для подтверждения оплаты
    ai_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-инструкция для бизнеса

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)  # Для оптимистичной блокировки

    # Связи
    owner: Mapped["User"] = relationship(back_populates="businesses")
    owners: Mapped[List["BusinessOwner"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    services: Mapped[List["Service"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    employees: Mapped[List["Employee"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    client_subscriptions: Mapped[List["ClientSubscription"]] = relationship(back_populates="business", cascade="all, delete-orphan")


class MarketingLead(Base):
    """Inbound ServGo business lead with minimal growth-attribution data."""
    __tablename__ = "marketing_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    experiment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    utm_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    utm_medium: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    utm_content: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    utm_term: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    self_reported_source: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    attribution_confidence: Mapped[str] = mapped_column(String(20), default="unverified")
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BusinessOwner(Base):
    """Множественные владельцы бизнеса"""
    __tablename__ = "business_owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner, co_owner
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    added_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (UniqueConstraint('business_id', 'user_id', name='uix_business_user'),)

    # Связи
    business: Mapped["Business"] = relationship(back_populates="owners")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    added_by: Mapped[Optional["User"]] = relationship(foreign_keys=[added_by_id])


class Service(Base):
    """Услуги бизнеса"""
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)  # Длительность в минутах
    price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Цена (можно в копейках)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_additional: Mapped[bool] = mapped_column(Boolean, default=False)  # Дополнительная услуга (для аренды)
    is_hourly_price: Mapped[bool] = mapped_column(Boolean, default=False)  # Цена за час (для доп. услуг venue_rental)
    available_employee_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON список ID сотрудников/залов, где доступна услуга (null = все)
    tariff_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Текст тарифов для контактных услуг (бронь через владельца)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # Порядок отображения (меньше = выше в списке)
    ai_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-инструкция
    version: Mapped[int] = mapped_column(Integer, default=1)  # Для оптимистичной блокировки
    pricing_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default='fixed')  # 'fixed' | 'per_person' — тип ценообразования
    group_pricing: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: [{"min_people":1,"max_people":3,"price":500}, ...] — тарифы по кол-ву человек

    # Связи
    business: Mapped["Business"] = relationship(back_populates="services")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    employees: Mapped[List["EmployeeService"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    subscription_services: Mapped[List["SubscriptionService"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    subscription_usages: Mapped[List["SubscriptionUsage"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class Employee(Base):
    """Сотрудники (мастера, администраторы, механики, специалисты)"""
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    specialization: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # Не unique - один человек может работать в нескольких бизнесах
    booking_interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Индивидуальный шаг записи
    role: Mapped[str] = mapped_column(String(20), default="master")  # master или administrator
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Venue rental fields
    capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Вместимость (чел.)
    area_sqm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Площадь (м²)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Описание зала
    min_booking_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Минимальное время бронирования
    solo_price_per_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Спецтариф соло (₽/час)
    photos: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON список file_id фото
    video: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # file_id видео
    on_duty_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)  # Дата дежурства
    duty_schedule: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: ["2026-03-25","2026-03-26",...] — график дежурств
    ai_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-инструкция
    services_text: Mapped[Optional[str]] = mapped_column("services", Text, nullable=True)  # JSON услуги (колонка "services", атрибут services_text чтобы не конфликтовать с relationship)

    # Связи
    business: Mapped["Business"] = relationship(back_populates="employees")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    days_off: Mapped[List["EmployeeDayOff"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    employee_services: Mapped[List["EmployeeService"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    time_pricing: Mapped[List["VenueTimePricing"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class VenueTimePricing(Base):
    """Тарифы аренды помещений по времени суток"""
    __tablename__ = "venue_time_pricing"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    time_from: Mapped[datetime.time] = mapped_column(Time)
    time_to: Mapped[datetime.time] = mapped_column(Time)
    price_per_hour: Mapped[int] = mapped_column(Integer)  # Цена за час
    day_type: Mapped[str] = mapped_column(String(20), default="all")  # all, weekday, weekend

    employee: Mapped["Employee"] = relationship(back_populates="time_pricing")


class Booking(Base):
    """Записи клиентов"""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    booking_date: Mapped[datetime.date] = mapped_column(Date)
    booking_time: Mapped[datetime.time] = mapped_column(Time)

    # Статусы: pending, confirmed, cancelled, completed,
    # pending_prepayment (ожидает предоплату), prepayment_sent (клиент отправил), prepayment_confirmed (владелец подтвердил)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Rental bookings have a per-booking duration/quote; ordinary services use service duration/price.
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Предоплата
    prepayment_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Сумма предоплаты
    prepayment_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Когда подтверждена

    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Deprecated, используем reminder_24h/2h
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Отправлено напоминание за 24ч
    reminder_2h_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Отправлено напоминание за 2ч
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)  # Для оптимистичной блокировки

    # Deep-link secret для подключения анонимного web-клиента к боту:
    # фронт показывает t.me/<bot>?start=notify_<token>, при /start клиент привязывается.
    notify_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Связь с использованием абонемента (если запись оплачена по абонементу)
    subscription_usage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subscription_usages.id", ondelete="SET NULL"), nullable=True)

    # Связи
    business: Mapped["Business"] = relationship(back_populates="bookings")
    client: Mapped["User"] = relationship(back_populates="bookings")
    service: Mapped["Service"] = relationship(back_populates="bookings")
    employee: Mapped["Employee"] = relationship(back_populates="bookings")
    subscription_usage: Mapped[Optional["SubscriptionUsage"]] = relationship(
        foreign_keys="[Booking.subscription_usage_id]",
        uselist=False
    )


class EmployeeDayOff(Base):
    """Выходные дни сотрудников"""
    __tablename__ = "employee_days_off"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    date: Mapped[datetime.date] = mapped_column(Date)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Причина (отпуск, больничный и т.д.)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    employee: Mapped["Employee"] = relationship(back_populates="days_off")


class EmployeeService(Base):
    """Связь между сотрудниками и услугами (какие услуги может делать мастер)"""
    __tablename__ = "employee_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    employee: Mapped["Employee"] = relationship(back_populates="employee_services")
    service: Mapped["Service"] = relationship(back_populates="employees")


class Subscription(Base):
    """Шаблон абонемента (создается владельцем бизнеса)"""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer)  # Цена абонемента
    validity_days: Mapped[int] = mapped_column(Integer)  # Срок действия в днях
    rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Правила применения
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ai_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-инструкция

    # Связи
    business: Mapped["Business"] = relationship(back_populates="subscriptions")
    services: Mapped[List["SubscriptionService"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    client_subscriptions: Mapped[List["ClientSubscription"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")


class SubscriptionService(Base):
    """Услуги, включенные в абонемент"""
    __tablename__ = "subscription_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # Количество этой услуги в абонементе

    # Связи
    subscription: Mapped["Subscription"] = relationship(back_populates="services")
    service: Mapped["Service"] = relationship(back_populates="subscription_services")


class ClientSubscription(Base):
    """Купленный абонемент клиента"""
    __tablename__ = "client_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))

    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # Дата истечения

    # Статусы: pending_payment, payment_sent, active, expired, depleted
    status: Mapped[str] = mapped_column(String(50), default="pending_payment")
    payment_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Когда владелец подтвердил оплату
    payment_receipt: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # file_id чека (фото/документ)
    expiry_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Напоминание о скором истечении

    # Связи
    subscription: Mapped["Subscription"] = relationship(back_populates="client_subscriptions")
    client: Mapped["User"] = relationship(back_populates="client_subscriptions")
    business: Mapped["Business"] = relationship(back_populates="client_subscriptions")
    usages: Mapped[List["SubscriptionUsage"]] = relationship(back_populates="client_subscription", cascade="all, delete-orphan")


class SubscriptionUsage(Base):
    """Использование услуги из абонемента"""
    __tablename__ = "subscription_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_subscription_id: Mapped[int] = mapped_column(ForeignKey("client_subscriptions.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    client_subscription: Mapped["ClientSubscription"] = relationship(back_populates="usages")
    service: Mapped["Service"] = relationship(back_populates="subscription_usages")
    booking: Mapped[Optional["Booking"]] = relationship(
        foreign_keys="[SubscriptionUsage.booking_id]",
        uselist=False
    )


class AuthPhoneCode(Base):
    """Одноразовые SMS-коды для phone-login.
    Заменяет in-memory _pending_codes в web/api/routes/auth.py — переживает рестарты API."""
    __tablename__ = "auth_phone_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
