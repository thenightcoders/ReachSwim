"""
Contact form emails.

  notify(msg)            — once a message reaches the inbox: a thank-you to
                           the sender, and a heads-up to the owners (all in
                           BCC, so nobody sees who else received it).
  quarantine_alert(...)  — asks the owners to look at messages stuck waiting
                           for the spam check.

Spam and quarantined messages never trigger ``notify``, so the site can't be
used to send email to someone who didn't write in.
"""
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.pages import mail


def _site_url() -> str:
    return getattr(settings, "SITE_URL", "") or "https://reachswim.co.uk"


def notify(msg) -> None:
    """Send both inbox emails, once per message, however many times it's called."""
    from apps.legal.models import ContactConfig, ContactMessage

    claimed = ContactMessage.objects.filter(pk=msg.pk, notified_at__isnull=True).update(notified_at=timezone.now())
    if not claimed:
        return

    context = {
        "msg": msg,
        # First word only, and short: the name is whatever the visitor typed.
        "first_name": (msg.name.split() or ["there"])[0][:30],
        "config": ContactConfig.load(),
        "site_url": _site_url(),
        "dashboard_url": _site_url() + reverse("dashboard:message_detail", args=[msg.pk]),
    }
    mail.send(
        subject="Thanks for getting in touch",
        body=render_to_string("emails/contact_thanks.txt", context),
        html=render_to_string("emails/contact_thanks.html", context),
        to=[msg.email],
    )
    owners = mail.owner_emails()
    if owners:
        mail.send(
            subject=f"New message from {msg.name[:60]}" + (f": {msg.subject[:80]}" if msg.subject else ""),
            body=render_to_string("emails/contact_new_message.txt", context),
            bcc=owners,
            reply_to=[msg.email],
        )


def quarantine_alert(count: int, oldest, status) -> None:
    owners = mail.owner_emails()
    if not owners:
        return
    mail.send(
        subject=f"{count} message{'s' if count != 1 else ''} waiting for the spam check",
        body=render_to_string("emails/contact_quarantine_alert.txt", {
            "count": count,
            "oldest": oldest,
            "status": status,
            "review_url": _site_url() + reverse("dashboard:messages") + "?show=quarantine",
        }),
        bcc=owners,
    )
