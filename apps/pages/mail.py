"""
One way to send an email from anywhere on the site.

  send(...)  — background email. Queued on django-q when
               settings.USE_DJANGO_Q_FOR_EMAILS is on, otherwise sent now.
  send_now() — sent during the request; use it when someone is waiting on
               the result (e.g. a dashboard "resend" button).
  render()    — renders emails/<name>.txt and .html with the brand context
               (logo, links, legal details) every email layout needs.

Both only take plain values (strings and lists), so the queued task never
has to pickle a model instance. Neither raises: a broken mail setup must
never break the page that triggered the email.
"""
import logging
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

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


def site_url() -> str:
    return getattr(settings, "SITE_URL", "") or "https://reachswim.co.uk"


def _absolute(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else site_url() + url


def brand_context() -> dict:
    """What emails/base.html needs: who we are, where to find us, the legal bits."""
    from apps.legal.models import LegalPage
    from apps.pages.models import SiteConfig

    site = SiteConfig.load()
    pages = set(LegalPage.objects.filter(is_active=True, slug__in=["privacy-policy", "terms"])
                .values_list("slug", flat=True))

    def page_url(slug):
        return _absolute(reverse("legal:page", args=[slug])) if slug in pages else ""

    return {
        "site": site,
        "site_url": site_url(),
        "site_host": site_url().split("://", 1)[-1],
        "logo_url": _absolute(site.logo.url if site.logo else static("img/logo.png")),
        "contact_url": _absolute(reverse("legal:contact")),
        "privacy_url": page_url("privacy-policy"),
        "terms_url": page_url("terms"),
        "year": timezone.localdate().year,
    }


def render(name: str, context: dict, *, html: bool = True) -> tuple[str, str]:
    """(text, html) for emails/<name>.txt and emails/<name>.html."""
    context = {**brand_context(), **context}
    text = render_to_string(f"emails/{name}.txt", context)
    return text, render_to_string(f"emails/{name}.html", context) if html else ""


def from_address() -> str:
    """DEFAULT_FROM_EMAIL with the business name in front, so inboxes show "ReachSwim"."""
    from apps.pages.models import SiteConfig

    address = settings.DEFAULT_FROM_EMAIL or "noreply@reachswim.co.uk"
    if parseaddr(address)[0]:
        return address
    try:
        return formataddr((SiteConfig.load().site_name, address))
    except Exception:
        return address


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
        from_email=from_address(),
        to=list(to),
        bcc=list(bcc),
        reply_to=list(reply_to) or None,
    )
    if html:
        msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)
