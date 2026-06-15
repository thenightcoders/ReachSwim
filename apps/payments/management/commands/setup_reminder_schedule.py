"""
Management command — register the payment reminder task with django_q2's
scheduler.  Run once after installing django-q2:

    pip install django-q2
    python manage.py migrate          # creates django_q tables
    python manage.py setup_reminder_schedule

Safe to re-run — uses get_or_create so it won't duplicate the schedule.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Register the send_pending_payment_reminders scheduled task with django_q2."

    def handle(self, *args, **options):
        try:
            from django_q.models import Schedule
        except ImportError:
            self.stdout.write(self.style.ERROR(
                "django-q2 is not installed. Run: pip install django-q2"
            ))
            return

        obj, created = Schedule.objects.get_or_create(
            name="send_pending_payment_reminders",
            defaults={
                "func": "apps.payments.tasks.send_pending_payment_reminders",
                "schedule_type": Schedule.HOURLY,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(
                "Schedule created — task runs every hour once qcluster is up.\n"
                "Start the worker with: python manage.py qcluster"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Schedule already exists (pk={obj.pk}). Nothing changed."
            ))
