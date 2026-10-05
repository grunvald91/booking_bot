"""
Pydantic schemas for request / response serialization.
"""
from __future__ import annotations

from datetime import date, time, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ---------- Auth ----------

class LoginPhoneIn(BaseModel):
    phone: str


class VerifyCodeIn(BaseModel):
    phone: str
    code: str


class AdminLoginIn(BaseModel):
    phone: str
    pin: str


class TelegramAuthIn(BaseModel):
    init_data: str


class UserOut(BaseModel):
    id: int
    full_name: str
    phone: Optional[str] = None
    username: Optional[str] = None

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    token: str
    user: UserOut
    role: str = "client"


# ---------- Business ----------

class GroupPricingTier(BaseModel):
    min_people: int = 1
    max_people: int = 1
    price: int = 0


class ServiceOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    price: Optional[int] = None
    is_active: bool = True
    is_additional: bool = False
    is_hourly_price: bool = False
    sort_order: int = 0
    pricing_type: Optional[str] = 'fixed'
    group_pricing: Optional[List[GroupPricingTier]] = None

    class Config:
        from_attributes = True


class TimePricingOut(BaseModel):
    time_from: str
    time_to: str
    price_per_hour: int
    day_type: str = "all"


class EmployeeOut(BaseModel):
    id: int
    name: str
    role: Optional[str] = "master"
    specialization: Optional[str] = None
    description: Optional[str] = None
    telegram_id: Optional[int] = None
    booking_interval_minutes: Optional[int] = None
    capacity: Optional[int] = None
    area_sqm: Optional[int] = None
    min_booking_minutes: Optional[int] = None
    solo_price_per_hour: Optional[int] = None
    photos: Optional[str] = None
    primary_photo: Optional[str] = None
    on_duty_date: Optional[date] = None
    is_active: bool = True
    venue_time_pricing: List[TimePricingOut] = []
    service_ids: List[int] = []

    class Config:
        from_attributes = True


class BusinessOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    business_type: str
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours_start: Optional[time] = None
    working_hours_end: Optional[time] = None
    photos: Optional[str] = None
    services_count: int = 0

    class Config:
        from_attributes = True


class BusinessDetailOut(BusinessOut):
    services: List[ServiceOut] = []
    employees: List[EmployeeOut] = []
    directions: Optional[str] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    prepayment_enabled: bool = False
    prepayment_percent: Optional[int] = None
    payment_phone: Optional[str] = None
    payment_details: Optional[str] = None
    cancellation_policy_photo: Optional[str] = None
    cancellation_policy_text: Optional[str] = None
    require_receipt_for_prepayment: bool = False
    booking_labels: dict[str, str] = Field(default_factory=dict)
    booking_flow_order: str = "service_first"


# ---------- Slots ----------

class SlotOut(BaseModel):
    time: str
    available: bool = True


# ---------- Bookings ----------

class PriceSegment(BaseModel):
    time_from: str
    time_to: str
    minutes: int
    price_per_hour: int
    subtotal: int


class CalculatePriceOut(BaseModel):
    has_time_price: bool
    total: int
    segments: List[PriceSegment] = []


class RescheduleIn(BaseModel):
    date: date
    time: str


class CreateBookingIn(BaseModel):
    business_id: int
    service_id: Optional[int] = None
    service_ids: List[int] = []
    additional_service_ids: List[int] = []
    additional_service_hours: Optional[dict] = None
    is_solo_booking: bool = False
    date: date
    time: str  # "HH:MM"
    employee_id: Optional[int] = None
    notes: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    # Повтор той же брони еженедельно на N недель (включая первую); None = без повтора.
    repeat_weeks: Optional[int] = Field(default=None, ge=2, le=8)


class BookingOut(BaseModel):
    id: int
    business_id: int = 0
    service_id: int = 0
    business_name: str
    service_name: str
    service_price: Optional[int] = None
    business_address: Optional[str] = None
    duration_minutes: Optional[int] = None
    date: date
    time: str
    status: str
    employee_name: Optional[str] = None
    employee_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    can_cancel: bool = False
    can_reschedule: bool = False
    notify_token: Optional[str] = None


class PublicServiceItem(BaseModel):
    name: str
    price: Optional[int] = None
    is_additional: bool = False


class PublicBookingOut(BaseModel):
    """Ответ GET /bookings/by-token/{token} — без данных клиента, только то,
    что нужно гостю без Telegram-логина, чтобы увидеть статус своей брони."""
    notify_token: str
    status: str
    business_name: str
    business_address: Optional[str] = None
    business_phone: Optional[str] = None
    business_directions: Optional[str] = None
    date: date
    time: str
    duration_minutes: int = 60
    employee_name: Optional[str] = None
    employee_label: str
    services: List[PublicServiceItem]
    total_price: int
    prepayment_enabled: bool = False
    prepayment_amount: int = 0
    paid_amount: int = 0
    prepayment_confirmed: bool = False
    payment_phone: Optional[str] = None
    payment_details: Optional[str] = None
    require_receipt_for_prepayment: bool = False
    cancellation_policy_text: Optional[str] = None
    cancellation_policy_photo: Optional[str] = None


# ---------- Admin ----------

class DashboardOut(BaseModel):
    today_bookings: int
    total_revenue: int
    pending_count: int
    confirmed_count: int


class AdminBookingOut(BaseModel):
    id: int
    client_name: str
    client_phone: Optional[str] = None
    service_name: str
    service_duration: Optional[int] = None
    price: Optional[int] = None
    is_rental: bool = False
    price_requires_confirmation: bool = False
    prepayment_amount: Optional[int] = None
    employee_name: Optional[str] = None
    employee_id: Optional[int] = None
    date: date
    time: str
    status: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ManualBookingIn(BaseModel):
    business_id: int
    service_id: int
    employee_id: Optional[int] = None
    date: date
    time: str
    client_name: str
    client_phone: Optional[str] = None
    notes: Optional[str] = None
    # Повтор той же брони еженедельно на N недель (включая первую); None = без повтора.
    repeat_weeks: Optional[int] = Field(default=None, ge=2, le=8)


class UpdateBookingStatusIn(BaseModel):
    status: str  # confirmed, completed, cancelled


class AdminRescheduleIn(BaseModel):
    """Перенос записи владельцем/админом (drag&drop в расписании)."""
    date: date
    time: str
    employee_id: Optional[int] = None  # необязательно: перенос на другого мастера/зал


class AnalyticsPointOut(BaseModel):
    date: date
    count: int


class AnalyticsKPIs(BaseModel):
    revenue: int
    bookings: int
    avg_check: int
    load_percent: Optional[float] = None
    revenue_prev: int
    bookings_prev: int
    avg_check_prev: int
    load_percent_prev: Optional[float] = None
    cancellation_rate: float
    cancelled_count: int
    cancellation_rate_prev: float
    cancelled_count_prev: int


class AnalyticsTopItem(BaseModel):
    id: int
    name: str
    count: int
    revenue: int
    share_percent: float


class AnalyticsDailyPoint(BaseModel):
    date: date
    bookings: int
    revenue: int
    cancelled: int


class AnalyticsPrepaymentStats(BaseModel):
    required_count: int
    confirmed_count: int
    conversion_rate: float
    avg_confirmation_minutes: Optional[float] = None


class AnalyticsHeatmapCell(BaseModel):
    day_of_week: int
    hour: int
    count: int


class AnalyticsOverviewOut(BaseModel):
    kpis: AnalyticsKPIs
    top_services: List[AnalyticsTopItem]
    top_employees: List[AnalyticsTopItem]
    daily: List[AnalyticsDailyPoint]
    prepayment: AnalyticsPrepaymentStats
    heatmap: List[AnalyticsHeatmapCell]


# ---------- Employee CRUD ----------

class EmployeeCreateIn(BaseModel):
    name: str
    role: str = "master"
    specialization: Optional[str] = None
    description: Optional[str] = None
    telegram_id: Optional[int] = None
    booking_interval_minutes: Optional[int] = None
    capacity: Optional[int] = None
    area_sqm: Optional[int] = None
    min_booking_minutes: Optional[int] = None
    solo_price_per_hour: Optional[int] = None


class EmployeeUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    specialization: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    telegram_id: Optional[int] = None
    booking_interval_minutes: Optional[int] = None
    capacity: Optional[int] = None
    area_sqm: Optional[int] = None
    min_booking_minutes: Optional[int] = None
    solo_price_per_hour: Optional[int] = None


# ---------- Service CRUD ----------

class ServiceCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    duration_minutes: int = 60
    price: Optional[int] = None
    is_active: bool = True
    is_additional: bool = False
    is_hourly_price: bool = False
    sort_order: int = 0
    pricing_type: Optional[str] = 'fixed'
    group_pricing: Optional[List[GroupPricingTier]] = None


class ServiceUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    price: Optional[int] = None
    is_active: Optional[bool] = None
    is_additional: Optional[bool] = None
    is_hourly_price: Optional[bool] = None
    sort_order: Optional[int] = None
    pricing_type: Optional[str] = None
    group_pricing: Optional[List[GroupPricingTier]] = None


# ---------- Subscriptions ----------

class SubscriptionServiceOut(BaseModel):
    id: int
    name: str
    quantity: int = 1


class SubscriptionOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: int
    validity_days: int
    services: List[SubscriptionServiceOut] = []
    is_active: bool = True

    class Config:
        from_attributes = True


class ClientSubscriptionOut(BaseModel):
    id: int
    subscription_name: str
    business_name: str
    status: str
    sessions_remaining: int = 0
    sessions_total: int = 0
    valid_until: Optional[datetime] = None
    payment_status: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------- Business Admin ----------

class BusinessUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours_start: Optional[str] = None  # "HH:MM"
    working_hours_end: Optional[str] = None
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    directions: Optional[str] = None
    booking_interval_minutes: Optional[int] = None
    prepayment_enabled: Optional[bool] = None
    prepayment_percent: Optional[int] = None
    payment_phone: Optional[str] = None
    payment_details: Optional[str] = None
    cancellation_policy_text: Optional[str] = None
    require_receipt_for_prepayment: Optional[bool] = None
    booking_labels: Optional[dict[str, str]] = None
    booking_flow_order: Optional[str] = None
    owner_reminders_enabled: Optional[bool] = None
    owner_reminder_minutes: Optional[List[int]] = None
    master_reminders_enabled: Optional[bool] = None
    master_reminder_minutes: Optional[List[int]] = None


class BusinessAdminDetailOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    business_type: str
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours_start: Optional[time] = None
    working_hours_end: Optional[time] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    booking_interval_minutes: int = 30
    directions: Optional[str] = None
    photos: Optional[str] = None
    video: Optional[str] = None
    prepayment_enabled: bool = False
    prepayment_percent: Optional[int] = None
    payment_phone: Optional[str] = None
    payment_details: Optional[str] = None
    cancellation_policy_photo: Optional[str] = None
    cancellation_policy_text: Optional[str] = None
    require_receipt_for_prepayment: bool = False
    booking_labels: dict[str, str] = Field(default_factory=dict)
    booking_flow_order: str = "service_first"
    owner_reminders_enabled: bool = True
    owner_reminder_minutes: List[int] = Field(default_factory=lambda: [1440, 120])
    master_reminders_enabled: bool = True
    master_reminder_minutes: List[int] = Field(default_factory=lambda: [1440, 120])

    class Config:
        from_attributes = True


# ---------- Owners ----------

class OwnerOut(BaseModel):
    id: int
    user_id: int
    role: str = "owner"
    user_name: str
    user_phone: Optional[str] = None
    telegram_id: Optional[int] = None
    added_at: Optional[datetime] = None


class OwnerAddIn(BaseModel):
    telegram_id: Optional[int] = None
    username: Optional[str] = None


# ---------- Venue Time Pricing CRUD ----------

class TimePricingCreateIn(BaseModel):
    time_from: str  # "HH:MM"
    time_to: str
    price_per_hour: int
    day_type: str = "all"


class TimePricingAdminOut(BaseModel):
    id: int
    time_from: str
    time_to: str
    price_per_hour: int
    day_type: str = "all"


# ---------- Employee-Service Link ----------

class EmployeeServiceLinkIn(BaseModel):
    service_ids: List[int]


class EmployeeServiceOut(BaseModel):
    service_id: int
    service_name: str


# ---------- Service Reorder ----------

class ServiceReorderIn(BaseModel):
    service_ids: List[int]  # ordered list of service IDs


# ---------- Subscription Admin CRUD ----------

class SubscriptionServiceIn(BaseModel):
    service_id: int
    quantity: int = 1


class SubscriptionCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    price: int
    validity_days: int
    rules: Optional[str] = None
    services: List[SubscriptionServiceIn] = []


class SubscriptionUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    validity_days: Optional[int] = None
    rules: Optional[str] = None
    is_active: Optional[bool] = None
    services: Optional[List[SubscriptionServiceIn]] = None


class SubscriptionAdminOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: int
    validity_days: int
    rules: Optional[str] = None
    is_active: bool = True
    services: List[SubscriptionServiceOut] = []

    class Config:
        from_attributes = True


# ---------- AI ----------

class AIChatIn(BaseModel):
    message: str
    business_id: Optional[int] = None


class AIChatOut(BaseModel):
    reply: str
    pending_action: Optional[dict] = None  # {action_id, description, tool_name, args}


class AIConfirmIn(BaseModel):
    action_id: str
