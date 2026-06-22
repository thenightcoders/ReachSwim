"""
Booking service — creates and cancels bookings, validates slot availability.
Thin views call this; this calls the availability service and ORM.

Email notifications are delegated to apps.booking.services.email — import
from there if you need to call them directly.
"""
import datetime
import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.booking.models import Booking, RecurringSchedule, SessionType, Location
from apps.booking.services.availability import get_slot, get_booking_settings

logger = logging.getLogger(__name__)


class SlotUnavailableError(Exception):
    """Raised when a slot doesn't exist or is full."""
    pass


class BookingValidationError(Exception):
    """Raised when booking data fails validation."""
    pass


class CancellationWindowError(Exception):
    """Raised when a cancellation is attempted outside the free-cancellation window."""
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
    user=None,
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
        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
    )
    return booking


def confirm_booking(booking: Booking, payment_intent_id: str = "") -> Booking:
    """Mark a booking as confirmed after successful payment."""
    from apps.booking.services.email import send_booking_confirmation
    from apps.booking.services import google_calendar

    booking.status = Booking.STATUS_CONFIRMED
    if payment_intent_id:
        booking.stripe_payment_intent_id = payment_intent_id
    booking.save(update_fields=["status", "stripe_payment_intent_id", "updated_at"])
    send_booking_confirmation(booking, async_send=True)

    event_id = google_calendar.create_event(booking)
    if event_id:
        booking.google_event_id = event_id
        booking.save(update_fields=["google_event_id"])

    return booking


def cancel_booking(
    booking: Booking,
    reason: str = "",
    notify_client: bool = True,
) -> Booking:
    """
    Cancel a booking.  Refund logic lives in the payments app.

    set notify_client=False when calling from expire_pending_orders() — those
    bookings were never confirmed so the client has no expectation of a session
    and a cancellation email would be confusing.
    """
    from apps.booking.services.email import send_booking_cancellation
    from apps.booking.services import google_calendar

    # Capture old status before we overwrite it — the email decision depends
    # on whether the booking was actually confirmed, not on STATUS_CANCELLED.
    was_confirmed = booking.status == Booking.STATUS_CONFIRMED

    booking.status = Booking.STATUS_CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason
    booking.save(update_fields=[
        "status", "cancelled_at", "cancellation_reason", "updated_at",
    ])

    if notify_client and was_confirmed:
        send_booking_cancellation(booking, async_send=True)

    google_calendar.delete_event(booking)

    return booking


def is_booking_cancellable(booking: Booking) -> bool:
    """
    Return True if the booking is in a state where the client can cancel for free.

    A booking is cancellable when:
      - status is STATUS_CONFIRMED
      - session start is still at least cancellation_hours in the future

    Single authoritative implementation — used by admin, views, and any
    future code that needs to check cancellability without touching the model layer.
    """
    if booking.status != Booking.STATUS_CONFIRMED:
        return False
    bs = get_booking_settings()
    session_dt = timezone.make_aware(
        datetime.datetime.combine(booking.date, booking.start_time)
    )
    cutoff = session_dt - datetime.timedelta(hours=bs.cancellation_hours)
    return timezone.now() < cutoff


def cancel_booking_for_client(booking: Booking, client_email: str) -> Booking:
    """
    Cancel a booking on behalf of a client, enforcing ownership and the
    cancellation window.

    Raises:
        PermissionError        — client_email doesn't match booking owner.
        ValueError             — booking is not in a cancellable status.
        CancellationWindowError — outside the free-cancellation window.
    """
    if booking.client_email.lower() != client_email.lower():
        raise PermissionError("You don't have permission to cancel this booking.")

    if booking.status not in (Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED):
        raise ValueError("This booking cannot be cancelled.")

    if not is_booking_cancellable(booking):
        bs = get_booking_settings()
        raise CancellationWindowError(
            f"Bookings can only be cancelled at least {bs.cancellation_hours} "
            f"hours before the session."
        )

    return cancel_booking(booking, reason="Cancelled by client via profile.")


def downgrade_to_draft(booking: Booking) -> Booking:
    """
    Downgrade a pending booking to STATUS_DRAFT when the cart TTL expires.

    Drafts:
      - never count toward slot capacity (excluded in count_for_slot)
      - survive until clean_draft_bookings purges them (configurable lifetime)
      - can be resumed by the client from their profile

    Only pending bookings with no linked OrderItem should be downgraded — a
    booking that reached checkout (has an OrderItem) should be cancelled instead
    because the user actively started payment.
    """
    booking.status = Booking.STATUS_DRAFT
    booking.save(update_fields=["status", "updated_at"])
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
