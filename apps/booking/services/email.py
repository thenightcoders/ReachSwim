"""
All outbound booking and payment emails live here — one place to find,
one place to change.

Public API:
  send_booking_confirmation(booking, *, async_send=False)
  send_booking_cancellation(booking, *, async_send=False)
  send_payment_reminder(booking, payment_link, *, async_send=False)

All functions:
  - Render HTML + plain-text templates from templates/emails/
  - Use EmailMultiAlternatives so clients that can't render HTML still get a
    readable message
  - Swallow SMTP exceptions and log them — a broken mail config must never
    kill a booking flow or block an HTTP response

async_send=True dispatches in a daemon thread (fire-and-forget, no return
value).  Use it from service code that doesn't need to know whether the mail
arrived.  Leave it False (default) when the caller checks the bool return —
e.g. the Django admin bulk-resend action.
"""
import logging
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _from_email() -> str:
    return settings.DEFAULT_FROM_EMAIL or "noreply@reachswim.co.uk"


def _admin_bcc() -> list[str]:
    """
    Return a BCC list containing the owner's email, or [] when not configured.
    Pulled from settings.ADMIN_EMAIL (set via ADMIN_EMAIL in .env).
    Centralised here so the rule is enforced once across every outgoing mail.
    """
    email = getattr(settings, "ADMIN_EMAIL", "")
    return [email] if email else []


def _send(
    *,
    subject: str,
    to: str,
    html_template: str,
    txt_template: str,
    context: dict,
) -> bool:
    """
    Render templates, build an EmailMultiAlternatives message, send it.
    The owner (ADMIN_EMAIL) is always BCC'd so every outgoing email lands
    silently in their inbox too.
    Returns True on success.  Never raises — logs the exception and returns
    False on any SMTP or template error.
    """
    try:
        html_body = render_to_string(html_template, context)
        txt_body  = render_to_string(txt_template,  context)

        bcc = _admin_bcc()
        msg = EmailMultiAlternatives(
            subject=subject,
            body=txt_body,
            from_email=_from_email(),
            to=[to],
            bcc=bcc,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        return True

    except Exception:
        logger.exception(
            "Failed to send '%s' to %s (html_template=%s)",
            subject, to, html_template,
        )
        return False


def _send_async(*, subject: str, to: str, html_template: str, txt_template: str, context: dict) -> None:
    """
    Dispatch _send() in a daemon thread — fire-and-forget.
    The thread is a daemon so it won't block process shutdown.
    Result is not available to the caller; failures are logged inside _send().
    """
    threading.Thread(
        target=_send,
        kwargs=dict(
            subject=subject,
            to=to,
            html_template=html_template,
            txt_template=txt_template,
            context=context,
        ),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Public send functions
# ---------------------------------------------------------------------------

def send_booking_confirmation(booking, *, async_send: bool = False) -> bool | None:
    """
    Send a booking confirmation email to the client.

    Called by confirm_booking() (async_send=True — non-blocking).
    Called by the admin bulk-resend action (async_send=False — checks return).

    Returns True/False when async_send=False, None when async_send=True.
    """
    context = _booking_context(booking)
    subject = f"Booking confirmed — {context['session_type_name']} on {context['date_str']}"
    kwargs  = dict(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_confirmation.html",
        txt_template="emails/booking_confirmation.txt",
        context=context,
    )

    if async_send:
        _send_async(**kwargs)
        return None
    return _send(**kwargs)


def send_booking_cancellation(booking, *, async_send: bool = False) -> bool | None:
    """
    Send a cancellation notification to the client.

    Called by cancel_booking() (async_send=True — non-blocking).

    Returns True/False when async_send=False, None when async_send=True.
    """
    context = _booking_context(booking)
    subject = f"Booking cancelled — {context['session_type_name']} on {context['date_str']}"
    kwargs  = dict(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_cancellation.html",
        txt_template="emails/booking_cancellation.txt",
        context=context,
    )

    if async_send:
        _send_async(**kwargs)
        return None
    return _send(**kwargs)


def send_refund_email(order, refund, *, order_item=None, async_send: bool = False) -> bool | None:
    """
    Send a refund confirmation email to the client.

    Works for all refund modes:
      • Per-item booking refund  → enriches context with booking details
      • Per-item product refund  → generic order-level context
      • Custom / full refund     → order-level context

    Called by apps.payments.services.refund._send_refund_email_async().

    Parameters
    ----------
    order       : The Order being refunded.
    refund      : The Refund record (duck-typed — avoids circular import).
    order_item  : The specific OrderItem being refunded, or None.

    Returns True/False when async_send=False, None when async_send=True.
    """
    client_name = order.client_name
    client_first_name = client_name.split()[0] if client_name else "there"

    context: dict = {
        "client_name":       client_name,
        "client_first_name": client_first_name,
        "order_number":      order.order_number,
        "refund_amount_str": f"£{refund.amount_pence / 100:.2f}",
        "stripe_refund_id":  refund.stripe_refund_id,
        # Item-level label for the email subject / header
        "item_label":        order_item.label if order_item else None,
    }

    # Enrich with booking details when this is a booking-item refund
    if order_item is not None and order_item.item_type == "booking" and order_item.booking:
        context.update(_booking_context(order_item.booking))
        subject = (
            f"Refund of {context['refund_amount_str']} processed — "
            f"{context['session_type_name']} on {context['date_str']}"
        )
    else:
        subject = f"Refund of {context['refund_amount_str']} processed — order #{order.order_number}"

    kwargs = dict(
        subject=subject,
        to=order.client_email,
        html_template="emails/booking_refund.html",
        txt_template="emails/booking_refund.txt",
        context=context,
    )

    if async_send:
        _send_async(**kwargs)
        return None
    return _send(**kwargs)


def send_payment_reminder(booking, payment_link: str, *, async_send: bool = False) -> bool | None:
    """
    Send a payment-reminder email to a client whose booking is pending payment.

    Called by apps.payments.services.reminder.send_payment_reminder_email().
    Uses async_send=True from the django_q2 task and from the dashboard manual
    send view — neither caller needs to block on SMTP.

    Returns True/False when async_send=False, None when async_send=True.
    """
    context = _booking_context(booking)
    context["payment_link"] = payment_link

    subject = f"Complete your booking — {context['session_type_name']} on {context['date_str']}"
    kwargs  = dict(
        subject=subject,
        to=booking.client_email,
        html_template="emails/payment_reminder.html",
        txt_template="emails/payment_reminder.txt",
        context=context,
    )

    if async_send:
        _send_async(**kwargs)
        return None
    return _send(**kwargs)


# ---------------------------------------------------------------------------
# Shared context builder
# ---------------------------------------------------------------------------

def _booking_context(booking) -> dict:
    """Build the shared template context for all booking emails."""
    session_type_name = (
        booking.session_type.name if booking.session_type_id else "Session"
    )
    location_name = (
        booking.location.name if booking.location_id else "Location TBC"
    )

    date_str  = booking.date.strftime("%A %-d %B %Y")
    start_str = booking.start_time.strftime("%-I:%M %p")
    end_str   = booking.end_time.strftime("%-I:%M %p") if booking.end_time else ""
    time_str  = f"{start_str}–{end_str}" if end_str else start_str
    amount_str = f"£{booking.amount_pence / 100:.2f}"

    return {
        "booking":            booking,
        "client_name":        booking.client_name,
        "client_first_name":  booking.client_name.split()[0] if booking.client_name else "there",
        "session_type_name":  session_type_name,
        "location_name":      location_name,
        "date_str":           date_str,
        "time_str":           time_str,
        "amount_str":         amount_str,
        "reference":          str(booking.reference),
        "cancellation_reason": getattr(booking, "cancellation_reason", ""),
    }
