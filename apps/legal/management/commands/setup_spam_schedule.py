"""
Register the contact form spam sweep with django-q's scheduler:

    python manage.py setup_spam_schedule

Every 10 minutes it re-checks messages waiting in quarantine and emails the
owner if they pile up. Safe to re-run.
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Register the contact form spam sweep with django-q."

    def handle(self, *args, **options):
        obj, created = Schedule.objects.update_or_create(
            name="contact_spam_sweep",
            defaults={
                "func": "apps.legal.tasks.sweep",
                "schedule_type": Schedule.MINUTES,
                "minutes": 10,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Spam sweep scheduled every 10 minutes (needs qcluster running)."))
        else:
            self.stdout.write(self.style.WARNING(f"Spam sweep schedule already exists (pk={obj.pk}); settings refreshed."))
