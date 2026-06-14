"""
Management command: expire_orders

Cancels pending bookings and orders abandoned at the Stripe checkout page.
Stripe sessions expire after 30 min; we use 35 min to give the webhook
a little slack before cleaning up.

Usage:
    python manage.py expire_orders
    python manage.py expire_orders --older-than 60

Cron (run every 10 minutes):
    */10 * * * * /path/to/venv/bin/python /path/to/manage.py expire_orders \
        --settings=config.settings.prod >> /var/log/reachswim/expire_orders.log 2>&1
"""
from django.core.management.base import BaseCommand

from apps.payments.services.checkout import expire_pending_orders


class Command(BaseCommand):
    help = (
        "Cancel pending bookings and orders abandoned at Stripe checkout "
        "(older than --older-than minutes, default 35)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=35,
            metavar="MINUTES",
            help="Cancel orders pending for longer than this many minutes (default: 35).",
        )

    def handle(self, *args, **options):
        count = expire_pending_orders(older_than_minutes=options["older_than"])
        if count:
            self.stdout.write(
                self.style.SUCCESS(f"Expired {count} stale order(s).")
            )
        else:
            self.stdout.write("No stale orders found.")
