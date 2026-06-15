"""
Payment reminder service.

Responsibilities (and only these):
  1. Build a signed payment link for a pending booking's Order.
  2. Dispatch the reminder email via the central email service.
  3. Record the send in the PaymentReminder audit log.

Email rendering and transport live in apps.booking.services.email —
nothing here calls send_mail or touches templates directly.

async_send behaviour
--------------------
  async_send=False (default, used by the django_q2 task):
    SMTP call is synchronous.  PaymentReminder is only created on success.
    If SMTP fails the record is withheld — the DB constraint doesn't block
    a retry on the next task run.

  async_send=True (used by the dashboard manual-send view):
    SMTP is dispatched in a daemon thread and the PaymentReminder is
    written optimistically.  The HTTP response is not held up by SMTP.
    On failure the log records it, but a second manual send is needed.
    Acceptable trade-off for a low-volume owner action.
"""
import logging

from django.conf import settings
from django.core import signing

from apps.payments.models import PaymentReminder, PaymentReminderRule

logger = logging.getLogger(__name__)

# Signed payment links are valid for 7 days.
REMINDER_LINK_MAX_AGE = 7 * 24 * 3600


def make_payment_link(booking) -> str:
    """
    Return a signed, tokenised URL the client can visit to complete payment.

    Encodes the Order reference so no Stripe session is pre-created —
    a fresh session is built on demand when the client clicks the link.

    Returns an empty string if the booking has no associated Order (e.g.
    it was created manually via the dashboard without going through checkout).
    """
    order_item = booking.order_items.select_related("order").first()
    if not order_item:
        logger.warning(
            "Booking %s has no OrderItem — cannot generate payment link.", booking.pk
        )
        return ""

    token = signing.dumps(str(order_item.order.reference), salt="payment-reminder")
    base  = settings.SITE_URL.rstrip("/")
    return f"{base}/pay/resume/{token}/"


def send_payment_reminder_email(
    booking,
    *,
    source: str = PaymentReminder.SOURCE_AUTO,
    rule: "PaymentReminderRule | None" = None,
    sent_by=None,
    async_send: bool = False,
) -> "PaymentReminder | None":
    """
    Orchestrate a single payment-reminder send:
      1. Build the payment link.
      2. Delegate email dispatch to the central email service.
      3. Record the send in PaymentReminder (on success).

    async_send=False (default):
      Sends synchronously.  PaymentReminder is only written if the email
      service reports success (returns True).  Safe for the task runner —
      a failed send leaves the DB constraint unblocked so the next run
      can retry.

    async_send=True:
      Sends in a background daemon thread and writes the PaymentReminder
      optimistically.  Use from HTTP views where SMTP latency must not
      hold up the response.

    Returns the created PaymentReminder on success, None otherwise.
    Callers must have already confirmed the booking is still pending.
    """
    from apps.booking.services.email import send_payment_reminder

    payment_link = make_payment_link(booking)
    if not payment_link:
        return None

    if async_send:
        # Fire-and-forget — optimistically record the send.
        send_payment_reminder(booking, payment_link, async_send=True)
        reminder = PaymentReminder.objects.create(
            booking=booking,
            rule=rule,
            source=source,
            sent_by=sent_by,
            email_sent_to=booking.client_email,
        )
        logger.info(
            "Payment reminder dispatched (async): booking=%s source=%s rule=%s to=%s",
            booking.pk, source, rule.pk if rule else None, booking.client_email,
        )
        return reminder

    # Synchronous path — only write the record when SMTP succeeds.
    success = send_payment_reminder(booking, payment_link, async_send=False)
    if not success:
        logger.warning(
            "Payment reminder SMTP failed: booking=%s source=%s rule=%s — no record written.",
            booking.pk, source, rule.pk if rule else None,
        )
        return None

    reminder = PaymentReminder.objects.create(
        booking=booking,
        rule=rule,
        source=source,
        sent_by=sent_by,
        email_sent_to=booking.client_email,
    )
    logger.info(
        "Payment reminder sent: booking=%s source=%s rule=%s to=%s",
        booking.pk, source, rule.pk if rule else None, booking.client_email,
    )
    return reminder
