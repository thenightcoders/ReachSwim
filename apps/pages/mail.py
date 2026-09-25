"""
One way to send an email from anywhere on the site.

  send(...)  — background email. Queued on django-q when
               settings.USE_DJANGO_Q_FOR_EMAILS is on, otherwise sent now.
  send_now() — sent during the request; use it when someone is waiting on
               the result (e.g. a dashboard "resend" button).

Both only take plain values (strings and lists), so the queued task never
has to pickle a model instance. Neither raises: a broken mail setup must
never break the page that triggered the email.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def owner_emails() -> list[str]:
    """ADMIN_EMAIL plus every active owner account, without duplicates."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    emails = [getattr(settings, "ADMIN_EMAIL", "")]
    emails += User.objects.filter(role=User.ROLE_OWNER, is_active=True).values_list("email", flat=True)
    seen, result = set(), []
    for email in emails:
        if email and email.lower() not in seen:
            seen.add(email.lower())
            result.append(email)
    return result


def send(*, subject: str, body: str, to=(), bcc=(), html: str = "", reply_to=()) -> bool | None:
    """Send in the background. Returns None when queued, else whether it went."""
    args = (subject, body, list(to), list(bcc), html, list(reply_to))
    if getattr(settings, "USE_DJANGO_Q_FOR_EMAILS", False):
        try:
            from django_q.tasks import async_task
            async_task("apps.pages.mail.deliver", *args)
            return None
        except Exception:
            logger.exception("Couldn't queue '%s'; sending it now instead", subject)
    return send_now(*args)


def send_now(subject, body, to=(), bcc=(), html="", reply_to=()) -> bool:
    try:
        deliver(subject, body, to, bcc, html, reply_to)
        return True
    except Exception:
        logger.exception("Failed to send '%s'", subject)
        return False


def deliver(subject, body, to, bcc, html, reply_to) -> None:
    """django-q task. Raises on failure, so it shows up as a failed task."""
    if not (to or bcc):
        return
    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL or "noreply@reachswim.co.uk",
        to=list(to),
        bcc=list(bcc),
        reply_to=list(reply_to) or None,
    )
    if html:
        msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)
