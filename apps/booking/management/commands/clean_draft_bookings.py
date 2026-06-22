"""
Management command — purge stale draft bookings.

Run on a schedule (daily cron / Celery beat):

    python manage.py clean_draft_bookings

Draft bookings are saved when a client's cart reservation expires before they
complete checkout.  They're kept for `BookingSettings.draft_lifetime_days`
(default 30) so the client can resume them from their profile.  After that
they're cancelled outright.

Exit codes:
  0 — completed (even if nothing was cleaned up)
"""
import datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Cancel draft bookings older than BookingSettings.draft_lifetime_days. "
        "Safe to run repeatedly — already-cancelled drafts are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be cancelled without touching the database.",
        )

    def handle(self, *args, **options):
        from apps.booking.models import Booking, BookingSettings
        from apps.booking.services.booking import cancel_booking

        settings = BookingSettings.load()
        lifetime_days = settings.draft_lifetime_days
        cutoff = timezone.now() - datetime.timedelta(days=lifetime_days)

        stale_drafts = Booking.objects.filter(
            status=Booking.STATUS_DRAFT,
            created_at__lt=cutoff,
        ).select_related("session_type", "location")

        count = stale_drafts.count()

        if count == 0:
            self.stdout.write("No stale draft bookings found.")
            return

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] Would cancel {count} draft booking(s) "
                    f"older than {lifetime_days} days:"
                )
            )
            for draft in stale_drafts:
                self.stdout.write(
                    f"  #{draft.pk} — {draft.session_type.name} @ {draft.location.name} "
                    f"{draft.date} {draft.start_time:%H:%M} (created {draft.created_at:%Y-%m-%d})"
                )
            return

        cancelled = 0
        errors = 0
        for draft in stale_drafts:
            try:
                cancel_booking(
                    draft,
                    reason=f"Draft expired after {lifetime_days} days.",
                    notify_client=False,
                )
                cancelled += 1
                logger.info(
                    "Cancelled stale draft booking #%s (%s @ %s, %s %s)",
                    draft.pk,
                    draft.session_type.name,
                    draft.location.name,
                    draft.date,
                    draft.start_time,
                )
            except Exception as exc:
                errors += 1
                logger.exception("Failed to cancel draft booking #%s: %s", draft.pk, exc)

        msg = f"Cancelled {cancelled} stale draft booking(s)."
        if errors:
            msg += f" {errors} error(s) — check logs."
            self.stderr.write(self.style.ERROR(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
