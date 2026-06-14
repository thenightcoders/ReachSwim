"""
Booking email notifications.

All outbound emails triggered by booking lifecycle events live here — one
place to find, one place to change.  Views and services import from this
module; nothing else should call send_mail directly for booking emails.

Functions:
  send_booking_confirmation(booking)  — called after confirm_booking()
  send_booking_cancellation(booking)  — called after cancel_booking()

Both functions:
  - Render HTML + plain-text templates from templates/emails/
  - Use Django's EmailMultiAlternatives so clients that can't render HTML
    still get a readable message
  - Swallow SMTP exceptions and log them — a broken mail config must never
    kill the booking flow
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _from_email() -> str:
    return settings.DEFAULT_FROM_EMAIL or "noreply@reachswim.co.uk"


def _send(
    subject: str,
    to: str,
    html_template: str,
    txt_template: str,
    context: dict,
) -> bool:
    """
    Internal helper — render templates, send, return True on success.
    Never raises; logs on failure.
    """
    try:
        html_body = render_to_string(html_template, context)
        txt_body = render_to_string(txt_template, context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=txt_body,
            from_email=_from_email(),
            to=[to],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        return True

    except Exception:
        logger.exception(
            "Failed to send '%s' to %s (template: %s)",
            subject, to, html_template,
        )
        return False


def send_booking_confirmation(booking) -> bool:
    """
    Send a booking confirmation email to the client.

    Called by confirm_booking() in apps/booking/services/booking.py after
    the booking status is flipped to STATUS_CONFIRMED.

    Returns True if the email was dispatched, False if SMTP failed.
    """
    context = _booking_context(booking)
    subject = f"Booking confirmed — {context['session_type_name']} on {context['date_str']}"

    return _send(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_confirmation.html",
        txt_template="emails/booking_confirmation.txt",
        context=context,
    )


def send_booking_cancellation(booking) -> bool:
    """
    Send a cancellation notification to the client.

    Called by cancel_booking() in apps/booking/services/booking.py after
    the booking status is flipped to STATUS_CANCELLED.

    Returns True if the email was dispatched, False if SMTP failed.
    """
    context = _booking_context(booking)
    subject = f"Booking cancelled — {context['session_type_name']} on {context['date_str']}"

    return _send(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_cancellation.html",
        txt_template="emails/booking_cancellation.txt",
        context=context,
    )


def _booking_context(booking) -> dict:
    """Build the shared template context for all booking emails."""
    session_type_name = (
        booking.session_type.name if booking.session_type_id else "Session"
    )
    location_name = (
        booking.location.name if booking.location_id else "Location TBC"
    )

    date_str = booking.date.strftime("%A %-d %B %Y")
    start_str = booking.start_time.strftime("%-I:%M %p")
    end_str = booking.end_time.strftime("%-I:%M %p") if booking.end_time else ""
    time_str = f"{start_str}–{end_str}" if end_str else start_str  # en dash
    amount_str = f"£{booking.amount_pence / 100:.2f}"  # £

    return {
        "booking": booking,
        "client_name": booking.client_name,
        "client_first_name": booking.client_name.split()[0] if booking.client_name else "there",
        "session_type_name": session_type_name,
        "location_name": location_name,
        "date_str": date_str,
        "time_str": time_str,
        "amount_str": amount_str,
        "reference": str(booking.reference),
        "cancellation_reason": getattr(booking, "cancellation_reason", ""),
    }
