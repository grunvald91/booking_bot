"""Shared ten-minute payment window for every booking channel and business type."""
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from database.models import Booking

PAYMENT_WINDOW = timedelta(minutes=10)


class PaymentWindowError(ValueError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def payment_deadline(booking):
    if booking.status != "pending_prepayment" or booking.prepayment_amount == 0:
        return None
    start = booking.prepayment_requested_at or booking.created_at
    return start + PAYMENT_WINDOW if start else None


def request_prepayment(booking, amount, *, now=None):
    """Start when an actual amount is requested; identical quotes do not extend it."""
    if amount < 0:
        raise ValueError("Negative prepayment")
    if amount > 0:
        if booking.status != "pending_prepayment" or booking.prepayment_amount != amount:
            booking.prepayment_requested_at = now or datetime.utcnow()
        booking.status = "pending_prepayment"
    elif booking.status == "pending_prepayment":
        booking.status = "pending"
        booking.prepayment_requested_at = None
    booking.prepayment_amount = amount


async def expire_due_prepayments(db, *, now=None):
    """Caller commits. Row locks serialize expiry with payment submission/confirmation."""
    now = now or datetime.utcnow()
    query = select(Booking).where(
        Booking.status == "pending_prepayment",
        or_(Booking.prepayment_amount.is_(None), Booking.prepayment_amount > 0),
        func.coalesce(Booking.prepayment_requested_at, Booking.created_at) <= now - PAYMENT_WINDOW,
    ).order_by(Booking.id).with_for_update().options(
        selectinload(Booking.client), selectinload(Booking.business), selectinload(Booking.service))
    expired = list((await db.execute(query)).scalars())
    for booking in expired:
        booking.status = "cancelled"
    return expired


async def require_payment_window(db, booking, *, receipt=False, now=None):
    """Routes load the booking FOR UPDATE first; never revive cancelled reservations."""
    if booking.status == "prepayment_sent":
        return False  # Idempotent retry; never turn receipt submission into payment confirmation.
    if booking.status != "pending_prepayment" or booking.prepayment_amount == 0:
        raise PaymentWindowError(409, "Эта запись не ожидает предоплаты")
    deadline = payment_deadline(booking)
    if deadline is not None and deadline <= (now or datetime.utcnow()):
        booking.status = "cancelled"
        await db.commit()
        raise PaymentWindowError(409, "Срок предоплаты истёк. Бронь отменена; выберите свободное время заново")
    if not receipt and booking.business.require_receipt_for_prepayment:
        raise PaymentWindowError(422, "Для отправки предоплаты необходимо приложить чек")
    return True
