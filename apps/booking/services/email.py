"""
All outbound booking and payment emails live here — one place to find,
one place to change.

Public API:
  send_booking_confirmation(booking, *, async_send=False)
  send_booking_cancellation(booking, *, async_send=False)
  send_payment_reminder(booking, payment_link, *, async_send=False)
  send_refund_email(order, refund, *, order_item=None, async_send=False)

All functions:
  - Render HTML + plain-text templates from templates/emails/
  - Use EmailMultiAlternatives so clients that can't render HTML still get a
    readable message
  - Swallow SMTP exceptions and log them — a broken mail config must never
    kill a booking flow or block an HTTP response

async_send=True dispatches via django_q2 (async_task) — the message is
serialised to the DB and a qcluster worker picks it up.  Tasks are retried
on failure, visible in the django_q admin, and survive process restarts.
Leave it False (default) when the caller needs to check the bool return —
e.g. the dashboard manual-send view that shows a success/failure flash.

Task entry points (_task_*) accept only primitive PKs — no model instances —
so django_q2's pickle-based serialisation never breaks on non-picklable
objects or stale in-memory state.
"""
import logging

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


# ---------------------------------------------------------------------------
# django_q2 task entry points — accept only PKs, never model instances
# ---------------------------------------------------------------------------

def _task_booking_confirmation(booking_pk: int) -> None:
    """django_q2 task: send booking confirmation email. Accepts PK only."""
    from apps.booking.models import Booking
    try:
        booking = Booking.objects.select_related("session_type", "location").get(pk=booking_pk)
    except Booking.DoesNotExist:
        logger.warning("_task_booking_confirmation: booking %s not found — skipping.", booking_pk)
        return
    send_booking_confirmation(booking, async_send=False)


def _task_booking_cancellation(booking_pk: int) -> None:
    """django_q2 task: send booking cancellation email. Accepts PK only."""
    from apps.booking.models import Booking
    try:
        booking = Booking.objects.select_related("session_type", "location").get(pk=booking_pk)
    except Booking.DoesNotExist:
        logger.warning("_task_booking_cancellation: booking %s not found — skipping.", booking_pk)
        return
    send_booking_cancellation(booking, async_send=False)


def _task_payment_reminder(booking_pk: int, payment_link: str) -> None:
    """django_q2 task: send payment reminder email. Accepts PK only."""
    from apps.booking.models import Booking
    try:
        booking = Booking.objects.select_related("session_type", "location").get(pk=booking_pk)
    except Booking.DoesNotExist:
        logger.warning("_task_payment_reminder: booking %s not found — skipping.", booking_pk)
        return
    send_payment_reminder(booking, payment_link, async_send=False)


def _task_refund_email(order_pk: int, refund_pk: int, order_item_pk: int | None) -> None:
    """django_q2 task: send refund confirmation email. Accepts PKs only."""
    from apps.payments.models import Order, OrderItem, Refund
    try:
        order  = Order.objects.get(pk=order_pk)
        refund = Refund.objects.get(pk=refund_pk)
        order_item = (
            OrderItem.objects.select_related("booking").get(pk=order_item_pk)
            if order_item_pk is not None
            else None
        )
    except (Order.DoesNotExist, Refund.DoesNotExist, OrderItem.DoesNotExist):
        logger.warning(
            "_task_refund_email: record not found "
            "(order_pk=%s refund_pk=%s order_item_pk=%s) — skipping.",
            order_pk, refund_pk, order_item_pk,
        )
        return
    send_refund_email(order, refund, order_item=order_item, async_send=False)


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
    if async_send:
        from django_q.tasks import async_task
        async_task(
            "apps.booking.services.email._task_booking_confirmation",
            booking.pk,
        )
        return None

    context = _booking_context(booking)
    subject = f"Booking confirmed — {context['session_type_name']} on {context['date_str']}"
    return _send(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_confirmation.html",
        txt_template="emails/booking_confirmation.txt",
        context=context,
    )


def send_booking_cancellation(booking, *, async_send: bool = False) -> bool | None:
    """
    Send a cancellation notification to the client.

    Called by cancel_booking() (async_send=True — non-blocking).

    Returns True/False when async_send=False, None when async_send=True.
    """
    if async_send:
        from django_q.tasks import async_task
        async_task(
            "apps.booking.services.email._task_booking_cancellation",
            booking.pk,
        )
        return None

    context = _booking_context(booking)
    subject = f"Booking cancelled — {context['session_type_name']} on {context['date_str']}"
    return _send(
        subject=subject,
        to=booking.client_email,
        html_template="emails/booking_cancellation.html",
        txt_template="emails/booking_cancellation.txt",
        context=context,
    )


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
    if async_send:
        from django_q.tasks import async_task
        async_task(
            "apps.booking.services.email._task_refund_email",
            order.pk,
            refund.pk,
            order_item.pk if order_item is not None else None,
        )
        return None

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

    return _send(
        subject=subject,
        to=order.client_email,
        html_template="emails/booking_refund.html",
        txt_template="emails/booking_refund.txt",
        context=context,
    )


def send_payment_reminder(booking, payment_link: str, *, async_send: bool = False) -> bool | None:
    """
    Send a payment-reminder email to a client whose booking is pending payment.

    Called by apps.payments.services.reminder.send_payment_reminder_email().
    async_send=True is used when the caller is a service/task that must not
    block on SMTP — the task is enqueued via django_q2 and retried on failure.
    async_send=False (default) is used by the django_q2 task worker itself
    and by the dashboard manual-send view (where the owner needs an immediate
    success/failure response).

    Returns True/False when async_send=False, None when async_send=True.
    """
    if async_send:
        from django_q.tasks import async_task
        async_task(
            "apps.booking.services.email._task_payment_reminder",
            booking.pk,
            payment_link,
        )
        return None

    context = _booking_context(booking)
    context["payment_link"] = payment_link

    subject = f"Complete your booking — {context['session_type_name']} on {context['date_str']}"
    return _send(
        subject=subject,
        to=booking.client_email,
        html_template="emails/payment_reminder.html",
        txt_template="emails/payment_reminder.txt",
        context=context,
    )


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
