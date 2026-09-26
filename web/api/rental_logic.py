"""Pure pricing and interval math shared by rental endpoints."""
from datetime import date, datetime, time, timedelta


def price_quote(hourly_rate: int, hours: int, fixed_addons: list[int]) -> tuple[int | None, bool, int]:
    """Return (quoted total or None, manager confirmation needed, fixed addon subtotal)."""
    if hourly_rate <= 0 or hours < 1 or hours > 12:
        raise ValueError('invalid rental rate or duration')
    addons = sum(fixed_addons)
    if hours < 5:
        return None, True, addons
    return hourly_rate * hours + addons, False, addons


def intervals_overlap(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and other_start < end


def available_starts(day: date, opens: time, closes: time, duration: int,
                     busy: list[tuple[time, int]], now: datetime | None = None) -> list[str]:
    """Return full-hour starts where the whole rental fits in business hours and is unbooked."""
    if duration < 60 or duration > 720 or duration % 60:
        raise ValueError('duration must be 1–12 whole hours')
    start_min = opens.hour * 60 + opens.minute
    end_min = closes.hour * 60 + closes.minute
    if end_min <= start_min:
        raise ValueError('overnight rental schedule is not supported')
    earliest = ((start_min + 59) // 60) * 60
    if now is not None:
        if day < now.date():
            return []
        if day == now.date():
            cutoff = now + timedelta(hours=1)
            earliest = max(earliest, ((cutoff.hour * 60 + cutoff.minute + (1 if cutoff.second or cutoff.microsecond else 0) + 59) // 60) * 60)
    occupied = [(t.hour * 60 + t.minute, t.hour * 60 + t.minute + minutes) for t, minutes in busy]
    return [f'{minute // 60:02d}:00' for minute in range(earliest, end_min - duration + 1, 60)
            if not any(intervals_overlap(minute, minute + duration, a, b) for a, b in occupied)]
