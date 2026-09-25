"""
django-q task entry points for the contact form spam check. Plain PKs only,
so nothing un-picklable ends up in the queue.
"""
from apps.legal.services import spam


def check_message(pk: int) -> None:
    """Queued for every new message."""
    from apps.legal.models import ContactMessage

    spam.check(ContactMessage.objects.filter(pk=pk))
    spam.maybe_alert()


def sweep() -> None:
    """Scheduled: retry whatever is still waiting, and nudge the owner if it piles up."""
    spam.check(spam.waiting()[:spam.SWEEP_SIZE])
    spam.maybe_alert()


def report(pks: list[int], is_spam: bool) -> None:
    from apps.legal.models import ContactMessage

    spam.report(ContactMessage.objects.filter(pk__in=pks), is_spam=is_spam)
