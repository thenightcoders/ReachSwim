"""
Availability service — expands recurring schedules into concrete slots,
checks capacity against existing bookings, respects booking-window limits.
"""
import datetime
from dataclasses import dataclass
from typing import List, Optional

from django.utils import timezone

from apps.booking.models import (
    BookingSettings,
    Booking,
    RecurringSchedule,
    SessionPricing,
    SessionType,
    Location,
)


# ---------------------------------------------------------------------------
# DTOs  (frozen — safe to cache, hash, pass around)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AvailableSlot:
    """One bookable time window on a specific date."""
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    session_type_id: int
    location_id: int
    max_capacity: int
    spots_taken: int
    price_pence: int

    @property
    def spots_remaining(self) -> int:
        return max(0, self.max_capacity - self.spots_taken)

    @property
    def is_available(self) -> bool:
        return self.spots_remaining > 0

    @property
    def price_display(self) -> str:
        return f"£{self.price_pence / 100:.2f}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_booking_settings() -> BookingSettings:
    return BookingSettings.load()


def _get_price(session_type_id: int, location_id: int) -> int:
    """Look up the price in pence for a session type at a location."""
    try:
        pricing = SessionPricing.objects.get(
            session_type_id=session_type_id,
            location_id=location_id,
        )
        return pricing.price_pence
    except SessionPricing.DoesNotExist:
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_available_dates(
    session_type: SessionType,
    location: Location,
) -> List[datetime.date]:
    """
    Return a sorted list of dates (from tomorrow up to max_advance_days)
    that have at least one recurring schedule for this session+location.
    """
    settings = get_booking_settings()
    now = timezone.now()
    start_date = now.date() + datetime.timedelta(days=1)
    end_date = now.date() + datetime.timedelta(days=settings.max_advance_days)

    # Which weekdays have schedules?
    active_days = set(
        RecurringSchedule.objects.filter(
            session_type=session_type,
            location=location,
            is_active=True,
        ).values_list("day_of_week", flat=True)
    )

    if not active_days:
        return []

    dates = []
    current = start_date
    while current <= end_date:
        if current.weekday() in active_days:
            dates.append(current)
        current += datetime.timedelta(days=1)

    return dates


def get_slots_for_date(
    session_type: SessionType,
    location: Location,
    date: datetime.date,
) -> List[AvailableSlot]:
    """
    Expand recurring schedules for a specific date into concrete slots,
    check capacity against existing bookings, and filter out slots whose
    start time has passed (respecting min_advance_hours).
    """
    settings = get_booking_settings()
    now = timezone.now()

    # The date must be within the booking window
    min_date = now.date()
    max_date = now.date() + datetime.timedelta(days=settings.max_advance_days)
    if date < min_date or date > max_date:
        return []

    # Get schedules for this weekday
    weekday = date.weekday()
    schedules = RecurringSchedule.objects.filter(
        session_type=session_type,
        location=location,
        day_of_week=weekday,
        is_active=True,
    )

    price = _get_price(session_type.id, location.id)

    slots = []
    for sched in schedules:
        # Check minimum advance time
        slot_dt = timezone.make_aware(
            datetime.datetime.combine(date, sched.start_time)
        )
        cutoff = now + datetime.timedelta(hours=settings.min_advance_hours)
        if slot_dt <= cutoff:
            continue

        taken = Booking.count_for_slot(
            session_type.id, location.id, date, sched.start_time,
        )

        slots.append(AvailableSlot(
            date=date,
            start_time=sched.start_time,
            end_time=sched.end_time,
            session_type_id=session_type.id,
            location_id=location.id,
            max_capacity=sched.max_capacity,
            spots_taken=taken,
            price_pence=price,
        ))

    return sorted(slots, key=lambda s: s.start_time)


def get_slot(
    session_type_id: int,
    location_id: int,
    date: datetime.date,
    start_time: datetime.time,
) -> Optional[AvailableSlot]:
    """
    Fetch a single slot — used during booking validation to confirm
    the slot still exists and has capacity.
    """
    try:
        session_type = SessionType.objects.get(pk=session_type_id, is_active=True)
        location = Location.objects.get(pk=location_id, is_active=True)
    except (SessionType.DoesNotExist, Location.DoesNotExist):
        return None

    slots = get_slots_for_date(session_type, location, date)
    for slot in slots:
        if slot.start_time == start_time:
            return slot
    return None
