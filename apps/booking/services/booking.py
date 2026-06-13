"""
Booking service — creates and cancels bookings, validates slot availability.
Thin views call this; this calls the availability service and ORM.
"""
import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.booking.models import Booking, RecurringSchedule, SessionType, Location
from apps.booking.services.availability import get_slot, get_booking_settings


class SlotUnavailableError(Exception):
    """Raised when a slot doesn't exist or is full."""
    pass


class BookingValidationError(Exception):
    """Raised when booking data fails validation."""
    pass


@transaction.atomic
def create_booking(
    session_type_id: int,
    location_id: int,
    date: datetime.date,
    start_time: datetime.time,
    client_name: str,
    client_email: str,
    client_phone: str = "",
    notes: str = "",
) -> Booking:
    """
    Validate and create a pending booking.
    Raises SlotUnavailableError if the slot is gone or full.

    Locks the RecurringSchedule row for this slot so that concurrent requests
    for the same slot queue up here rather than racing past the capacity check.
    """
    # Acquire a row-level lock on the schedule entry for this slot.
    # All concurrent booking attempts for the same slot will block here until
    # the current transaction commits or rolls back.
    try:
        RecurringSchedule.objects.select_for_update().get(
            session_type_id=session_type_id,
            location_id=location_id,
            day_of_week=date.weekday(),
            start_time=start_time,
            is_active=True,
        )
    except RecurringSchedule.DoesNotExist:
        raise SlotUnavailableError(
            "This slot is no longer available. Please choose another time."
        )

    # Re-check availability with the lock held — capacity may have changed
    # while we were waiting for the lock.
    slot = get_slot(session_type_id, location_id, date, start_time)
    if slot is None or not slot.is_available:
        raise SlotUnavailableError(
            "This slot is no longer available. Please choose another time."
        )

    booking = Booking.objects.create(
        session_type_id=session_type_id,
        location_id=location_id,
        date=date,
        start_time=start_time,
        end_time=slot.end_time,
        client_name=client_name.strip(),
        client_email=client_email.strip().lower(),
        client_phone=client_phone.strip(),
        amount_pence=slot.price_pence,
        status=Booking.STATUS_PENDING,
        notes=notes.strip(),
    )
    return booking


def confirm_booking(booking: Booking, payment_intent_id: str = "") -> Booking:
    """Mark a booking as confirmed after successful payment."""
    booking.status = Booking.STATUS_CONFIRMED
    if payment_intent_id:
        booking.stripe_payment_intent_id = payment_intent_id
    booking.save(update_fields=["status", "stripe_payment_intent_id", "updated_at"])
    return booking


def cancel_booking(
    booking: Booking,
    reason: str = "",
) -> Booking:
    """
    Cancel a booking.  Refund logic lives in the payments app.
    """
    booking.status = Booking.STATUS_CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason
    booking.save(update_fields=[
        "status", "cancelled_at", "cancellation_reason", "updated_at",
    ])
    return booking


def complete_booking(booking: Booking) -> Booking:
    """Mark a booking as completed (session took place)."""
    booking.status = Booking.STATUS_COMPLETED
    booking.save(update_fields=["status", "updated_at"])
    return booking


def get_booking_by_reference(reference: str) -> Optional[Booking]:
    """Fetch a booking by its UUID reference."""
    try:
        return Booking.objects.select_related(
            "session_type", "location",
        ).get(reference=reference)
    except Booking.DoesNotExist:
        return None
