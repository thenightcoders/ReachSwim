"""
Contact form spam screening.

One responsibility: decide which folder a contact form message belongs in.

When it is sent, ``screen`` runs the quick checks:

  drop       — certainly a bot (trap field filled, or sent too fast). Nothing
               is saved, but the sender still sees the normal "thanks"
               message so the bot learns nothing.
  limit      — too many messages from the same address in the last hour.
  spam       — saved straight to Spam: banned sender, or too many links.
  quarantine — saved, waiting for the spam detection API.
  ok         — saved to the inbox (only when the API is switched off).

Then ``queue_check`` asks a django-q worker to run ``check``, which calls the
spam detection API (settings.SPAM_DETECTION_URL) and moves the message to the
inbox or to Spam. If the API is down nothing is lost: the message waits in
quarantine, a scheduled sweep retries it, and ``maybe_alert`` emails the owner
if messages pile up. Messages already in Spam are checked too, only to record
their score.

With settings.SPAM_DETECTION_API_KEY set, batches go through the bulk
endpoints; without one (or if the key is refused) messages go one by one.
"""
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from functools import reduce
from operator import or_
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMESTAMP_SALT = "legal.contact.rendered-at"
MIN_SECONDS = 3            # humans can't fill the form faster than this
MAX_PER_HOUR = 5           # messages per IP address
MAX_LINKS = 2              # links to other websites; more and it's spam
API_TIMEOUT = 4            # seconds
BULK_SIZE = 100            # the API's per-request item cap
SWEEP_SIZE = 100           # messages per scheduled sweep
MAX_SPAM_CHECKS = 3        # tries at scoring a message that is already in Spam
ALERT_COUNT = 5            # this many waiting in quarantine emails the owner...
ALERT_AGE = timedelta(hours=1)      # ...as does one waiting this long
ALERT_EVERY = timedelta(hours=24)   # at most one alert email per day

LINK_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


@dataclass
class Verdict:
    action: str                 # "drop" | "limit" | "spam" | "quarantine" | "ok"
    reason: str = ""            # ContactMessage.spam_reason for "spam"


@dataclass
class CheckRun:
    """What one ``check`` call did, for the dashboard's flash message."""
    api_ok: bool | None = None  # None: the API is switched off
    to_inbox: int = 0
    to_spam: int = 0
    scored: int = 0             # already in Spam, score recorded
    waiting: int = 0            # still in quarantine
    busy: bool = False          # the API said "too many requests"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sign_render_time() -> str:
    """Value for the form's hidden timestamp field."""
    return signing.dumps(time.time(), salt=TIMESTAMP_SALT)


def seconds_since_render(token: str) -> float | None:
    """None when the token is missing or tampered with."""
    try:
        return time.time() - float(signing.loads(token, salt=TIMESTAMP_SALT))
    except (signing.BadSignature, TypeError, ValueError):
        return None


def client_ip(request) -> str | None:
    """
    The visitor's IP. Behind nginx, REMOTE_ADDR is the proxy, so use the last
    X-Forwarded-For entry (the one nginx appended, which the visitor can't fake).
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _own_hosts() -> set[str]:
    hosts = {urlsplit(getattr(settings, "SITE_URL", "")).hostname or ""}
    hosts.update(h.lstrip(".") for h in settings.ALLOWED_HOSTS if h != "*")
    return {h.lower().removeprefix("www.") for h in hosts if h}


def count_links(text: str) -> int:
    """Links in ``text``, not counting links to this website."""
    own = _own_hosts()
    count = 0
    for link in LINK_RE.findall(text):
        host = (urlsplit(link if "://" in link else f"http://{link}").hostname or "").removeprefix("www.")
        if not any(host == h or host.endswith(f".{h}") for h in own):
            count += 1
    return count


def enabled() -> bool:
    return bool(getattr(settings, "SPAM_DETECTION_URL", ""))


def _request(path: str, payload=None, *, use_key=True) -> tuple[int, dict | None]:
    """
    Call the API. Returns (HTTP status, JSON body); status 0 when it couldn't
    be reached at all. Never raises.
    """
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    api_key = getattr(settings, "SPAM_DETECTION_API_KEY", "")
    if use_key and api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(
        f"{settings.SPAM_DETECTION_URL.rstrip('/')}{path}", data=data, headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"null")
        except ValueError:
            body = None
        logger.warning("Spam detection API %s answered %s", path, exc.code)
        return exc.code, body
    except Exception as exc:  # network, timeout, bad JSON
        logger.warning("Spam detection API %s unreachable: %s", path, exc)
        return 0, None


def _record(ok: bool, error: str = "") -> None:
    from apps.legal.models import SpamCheckStatus

    status = SpamCheckStatus.load()
    now = timezone.now()
    status.api_ok = ok
    status.last_checked_at = now
    status.last_error = "" if ok else error[:300]
    if ok:
        status.last_ok_at = now
    status.save()


def _describe(code: int) -> str:
    if code == 0:
        return "Couldn't reach the spam check service."
    if code == 429:
        return "The spam check service is busy (too many requests)."
    if code in (401, 403):
        return "The spam check service refused the API key."
    return f"The spam check service answered with an error ({code})."


def health() -> bool:
    """Ask /health/ whether the API can classify right now, and remember it."""
    code, body = _request("/health/", use_key=False)
    ok = code == 200 and bool(body) and body.get("status") == "ok"
    if ok:
        _record(True)
    elif code == 503 and body:
        down = ", ".join(k for k, v in (body.get("checks") or {}).items() if v != "ok")
        _record(False, f"The spam check service is unhealthy ({down or 'unknown'}).")
    else:
        _record(False, _describe(code))
    return ok


def _payload(msg) -> dict:
    item = {
        "text": msg.message[:10000],
        "subject": msg.subject,
        "name": msg.name,
        "email": msg.email,
        "user_agent": msg.user_agent,
        "external_id": f"contact-{msg.pk}",
    }
    if msg.ip_address:
        item["ip"] = msg.ip_address
    return item


# ---------------------------------------------------------------------------
# When a message is sent
# ---------------------------------------------------------------------------

def screen(request, data: dict, trap: str, rendered_at: str) -> Verdict:
    """Run the quick checks, cheapest first. ``data`` is the form's cleaned_data."""
    from apps.legal.models import BannedSender, ContactMessage

    if trap:
        return Verdict("drop")

    age = seconds_since_render(rendered_at)
    if age is None or age < MIN_SECONDS:
        return Verdict("drop")

    ip = client_ip(request)
    if ip:
        recent = ContactMessage.objects.filter(
            ip_address=ip, created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()
        if recent >= MAX_PER_HOUR:
            return Verdict("limit")

    if BannedSender.is_banned(data.get("email", "")):
        return Verdict("spam", reason="banned")

    if count_links(f"{data.get('subject', '')} {data.get('message', '')}") > MAX_LINKS:
        return Verdict("spam", reason="links")

    return Verdict("quarantine") if enabled() else Verdict("ok")


def queue_check(msg) -> None:
    """Ask a django-q worker to check this message. The sweep catches misses."""
    if not enabled():
        return
    try:
        from django_q.tasks import async_task
        async_task("apps.legal.tasks.check_message", msg.pk)
    except Exception:
        logger.exception("Couldn't queue the spam check for message %s", msg.pk)


# ---------------------------------------------------------------------------
# Checking with the API
# ---------------------------------------------------------------------------

def waiting():
    """Messages the API hasn't answered for yet: quarantine, then unscored spam."""
    from apps.legal.models import ContactMessage

    return ContactMessage.objects.filter(
        Q(quarantined=True, is_spam=False)
        | Q(is_spam=True, checked_at__isnull=True, check_attempts__lt=MAX_SPAM_CHECKS)
    ).order_by("-quarantined", "created_at")


def check(messages) -> CheckRun:
    """
    Check ``messages`` with the API and file them. Health first, so a down
    API costs one request rather than one per message.
    """
    messages = [m for m in messages if m.quarantined or (m.is_spam and m.checked_at is None)]
    run = CheckRun(waiting=sum(m.quarantined for m in messages))
    if not enabled():
        return run
    run.api_ok = health()
    if not run.api_ok or not messages:
        return run

    by_id = {f"contact-{m.pk}": m for m in messages}
    pending = list(messages)
    if getattr(settings, "SPAM_DETECTION_API_KEY", ""):
        pending = _check_bulk(pending, by_id, run)
    for msg in pending:
        if run.busy:
            break
        code, body = _request("/v2/check-spam/", _payload(msg))
        if code == 429:
            run.busy = True
        _file(msg, body if code == 200 else None, run)
    if run.busy:
        _record(False, _describe(429))
    return run


def _check_bulk(messages, by_id, run) -> list:
    """Returns the messages the bulk endpoint didn't handle."""
    for start in range(0, len(messages), BULK_SIZE):
        chunk = messages[start:start + BULK_SIZE]
        code, body = _request("/v2/check-spam/bulk/", {"items": [_payload(m) for m in chunk]})
        if code in (401, 403):
            logger.warning("Bulk spam check refused the API key; checking one by one")
            return messages[start:]
        if code == 429:
            run.busy = True
            return []
        results = {r.get("external_id"): r for r in (body or {}).get("results", [])} if code == 200 else {}
        for msg in chunk:
            _file(msg, results.get(f"contact-{msg.pk}"), run)
    return []


def _file(msg, result: dict | None, run: CheckRun) -> None:
    """Apply one API answer (None when it failed) to the message."""
    from apps.legal.models import ContactMessage
    from apps.legal.services import contact_email

    found_in = {"is_spam": msg.is_spam, "quarantined": msg.quarantined}
    fields = ["check_attempts"]
    msg.check_attempts += 1
    if result and result.get("success"):
        msg.spam_score = result.get("spam_score")
        msg.checked_at = timezone.now()
        fields += ["spam_score", "checked_at"]
        if msg.quarantined:
            msg.quarantined = False
            fields.append("quarantined")
            run.waiting -= 1
            if result.get("is_spam"):
                msg.is_spam, msg.spam_reason = True, "detector"
                fields += ["is_spam", "spam_reason"]
                run.to_spam += 1
            else:
                run.to_inbox += 1
        else:
            run.scored += 1
    # Only touch the message if it's still where we found it (the owner may
    # have filed it while the API was thinking).
    updated = ContactMessage.objects.filter(pk=msg.pk, **found_in).update(**{f: getattr(msg, f) for f in fields})
    if updated and msg.folder == "inbox":
        contact_email.notify(msg)


def maybe_alert() -> bool:
    """
    Email the owner when messages pile up in quarantine (too many, or waiting
    too long), at most once a day. Returns True when an email was sent.
    """
    from apps.legal.models import ContactMessage, SpamCheckStatus
    from apps.legal.services import contact_email

    status = SpamCheckStatus.load()
    waiting_qs = ContactMessage.objects.quarantine()
    count = waiting_qs.count()
    if not count:
        if status.alert_sent_at:  # all clear: the next pile-up alerts straight away
            status.alert_sent_at = None
            status.save(update_fields=["alert_sent_at"])
        return False

    now = timezone.now()
    oldest = waiting_qs.order_by("created_at").values_list("created_at", flat=True).first()
    if count < ALERT_COUNT and now - oldest < ALERT_AGE:
        return False
    if status.alert_sent_at and now - status.alert_sent_at < ALERT_EVERY:
        return False

    contact_email.quarantine_alert(count, oldest, status)
    status.alert_sent_at = now
    status.save(update_fields=["alert_sent_at"])
    return True


# ---------------------------------------------------------------------------
# The owner's decisions
# ---------------------------------------------------------------------------

def move(qs, folder: str) -> int:
    """
    File messages into "inbox" or "spam" for the owner, and teach the API the
    answer. Messages arriving in the inbox for the first time are notified.
    Returns how many moved.
    """
    from apps.legal.services import contact_email

    if folder == "spam":
        changed = list(qs.exclude(is_spam=True))
        qs.filter(pk__in=[m.pk for m in changed]).update(is_spam=True, quarantined=False, spam_reason="owner")
    else:
        changed = list(qs.filter(Q(is_spam=True) | Q(quarantined=True)))
        qs.filter(pk__in=[m.pk for m in changed]).update(is_spam=False, quarantined=False, spam_reason="")
        for msg in changed:
            contact_email.notify(msg)
    queue_report(changed, is_spam=folder == "spam")
    return len(changed)


def ban(emails) -> int:
    """
    Ban these sender addresses and move every message from them to Spam.
    Returns how many messages moved.
    """
    from apps.legal.models import BannedSender, ContactMessage

    emails = {e.strip().lower() for e in emails if e and e.strip()}
    if not emails:
        return 0
    for email in emails:
        BannedSender.objects.get_or_create(email=email)
    qs = ContactMessage.objects.filter(reduce(or_, (Q(email__iexact=e) for e in emails)))
    changed = list(qs.exclude(is_spam=True))
    qs.filter(pk__in=[m.pk for m in changed]).update(is_spam=True, quarantined=False, spam_reason="banned")
    queue_report(changed, is_spam=True)
    return len(changed)


def unban(email) -> None:
    """Future messages are screened as normal. Existing ones stay in Spam."""
    from apps.legal.models import BannedSender

    BannedSender.objects.filter(email=email.strip().lower()).delete()


def queue_report(messages, is_spam: bool) -> None:
    """Report in the background; the API can be slow and the owner is waiting."""
    pks = [m.pk for m in messages]
    if not pks or not enabled():
        return
    try:
        from django_q.tasks import async_task
        async_task("apps.legal.tasks.report", pks, is_spam)
    except Exception:
        logger.exception("Couldn't queue the spam report; sending it now")
        report(messages, is_spam)


def report(messages, is_spam: bool) -> None:
    """
    Tell the spam detection API the owner's verdict on these messages, so its
    model learns from both mistakes and confirmations.
    """
    items = [
        {"message": m.message[:10000], "subject": m.subject[:500], "is_spam": is_spam,
         "external_id": f"contact-{m.pk}"}
        for m in messages if m.message.strip()
    ]
    if not items or not enabled():
        return
    if getattr(settings, "SPAM_DETECTION_API_KEY", ""):
        for start in range(0, len(items), BULK_SIZE):
            code, _ = _request("/v2/suggestion/bulk/", {"items": items[start:start + BULK_SIZE]})
            if code in (401, 403):
                items = items[start:]
                break
            if code == 429:
                return
        else:
            return
    for item in items:
        code, _ = _request("/v2/suggestion/", item)
        if code == 429:
            return
