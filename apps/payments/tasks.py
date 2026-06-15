"""
django_q2 tasks for the payments app.

Register the schedule once (via management command or shell) — the task
runner picks it up automatically on every subsequent qcluster run:

    from django_q.models import Schedule
    Schedule.objects.get_or_create(
        name="send_pending_payment_reminders",
        defaults=dict(
            func="apps.payments.tasks.send_pending_payment_reminders",
            schedule_type=Schedule.HOURLY,
        ),
    )
"""
import datetime
import logging

from django.utils import timezone

from apps.booking.models import Booking
from apps.payments.models import PaymentReminder, PaymentReminderRule
from apps.payments.services.reminder import send_payment_reminder_email

logger = logging.getLogger(__name__)


def send_pending_payment_reminders() -> dict:
    """
    Evaluate every active PaymentReminderRule against all pending bookings
    and send emails where due.

    Each rule fires at most once per booking (enforced by the DB unique
    constraint on PaymentReminder).  This function is idempotent — safe to
    run more frequently than the smallest delay_hours value.

    Returns a summary dict for django_q2 task result storage.
    """
    now = timezone.now()
    rules = PaymentReminderRule.objects.filter(is_active=True)

    if not rules.exists():
        logger.info("No active payment reminder rules — nothing to do.")
        return {"sent": 0, "skipped": 0, "errors": 0}

    sent = skipped = errors = 0

    for rule in rules:
        # Exclude bookings that already received this rule's email via a DB
        # subquery — avoids loading all-time reminder IDs into Python memory.
        base_qs = (
            Booking.objects
            .filter(status=Booking.STATUS_PENDING)
            .exclude(payment_reminders__rule=rule)
            .select_related("session_type", "location")
        )

        if rule.delay_anchor == PaymentReminderRule.ANCHOR_CREATED:
            # Fire when the booking is at least delay_hours old.
            threshold = now - datetime.timedelta(hours=rule.delay_hours)
            bookings = list(
                base_qs.filter(
                    created_at__lte=threshold,
                    date__gte=now.date(),   # session still upcoming
                )
            )

        else:  # ANCHOR_SESSION
            # Fire when fewer than delay_hours remain before the session starts.
            fire_before = now + datetime.timedelta(hours=rule.delay_hours)

            # Coarse SQL filter on date — SQLite cannot combine DateField +
            # TimeField into a single datetime for comparison.
            candidates = list(
                base_qs.filter(
                    date__lte=fire_before.date(),
                    date__gte=now.date(),
                )
            )
            # Refine in Python: exclude sessions beyond the time window.
            bookings = [
                b for b in candidates
                if datetime.datetime.combine(
                    b.date, b.start_time,
                    tzinfo=now.tzinfo,
                ) <= fire_before
            ]

        for booking in bookings:
            try:
                # async_send=False: the task worker is the background context;
                # blocking on SMTP is fine and lets us only write the
                # PaymentReminder record on confirmed delivery.
                result = send_payment_reminder_email(
                    booking, source=PaymentReminder.SOURCE_AUTO, rule=rule, async_send=False
                )
                if result:
                    sent += 1
                else:
                    skipped += 1
            except Exception:
                logger.exception(
                    "Unexpected error sending reminder: booking=%s rule=%s",
                    booking.pk, rule.pk,
                )
                errors += 1

    logger.info(
        "send_pending_payment_reminders complete: sent=%d skipped=%d errors=%d",
        sent, skipped, errors,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}
