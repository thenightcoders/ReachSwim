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
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.pages import mail


def notify(msg) -> None:
    """Send both inbox emails, once per message, however many times it's called."""
    from apps.legal.models import ContactConfig, ContactMessage

    claimed = ContactMessage.objects.filter(pk=msg.pk, notified_at__isnull=True).update(notified_at=timezone.now())
    if not claimed:
        return

    config = ContactConfig.load()
    # First word only, and short: the name is whatever the visitor typed.
    first_name = (msg.name.split() or ["there"])[0][:30]
    subject = f"Re: {msg.subject}" if msg.subject else f"Your message to {mail.brand_context()['site'].site_name}"
    context = {
        "msg": msg,
        "first_name": first_name,
        "config": config,
        "sent_str": date_format(timezone.localtime(msg.created_at), "l j F Y, H:i"),
        "dashboard_url": mail.site_url() + reverse("dashboard:message_detail", args=[msg.pk]),
        "reply_url": f"mailto:{quote(msg.email, safe='@')}?subject={quote(subject)}",
        "reply_label": f"Reply to {first_name}",
    }
    text, html = mail.render("contact_thanks", context)
    mail.send(
        subject="Thanks for getting in touch",
        body=text,
        html=html,
        to=[msg.email],
        reply_to=[config.email],
    )
    owners = mail.owner_emails()
    if owners:
        text, html = mail.render("contact_new_message", context)
        mail.send(
            subject=f"New message from {msg.name[:60]}" + (f": {msg.subject[:80]}" if msg.subject else ""),
            body=text,
            html=html,
            bcc=owners,
            reply_to=[msg.email],
        )


def quarantine_alert(count: int, oldest, status) -> None:
    owners = mail.owner_emails()
    if not owners:
        return
    text, html = mail.render("contact_quarantine_alert", {
        "count": count,
        "oldest": oldest,
        "status": status,
        "review_url": mail.site_url() + reverse("dashboard:messages") + "?show=quarantine",
    })
    mail.send(
        subject=f"{count} message{'s' if count != 1 else ''} waiting for the spam check",
        body=text,
        html=html,
        bcc=owners,
    )
