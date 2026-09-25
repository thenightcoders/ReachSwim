"""
Contact form spam screening.

One responsibility: decide what happens to a contact form submission.

  drop  — certainly a bot (trap field filled, or sent too fast). Nothing is
          saved, but the sender still sees the normal "thanks" message so the
          bot learns nothing.
  limit — too many messages from the same address in the last hour.
  spam  — saved, but filed under Spam in the dashboard (too many links, or
          the spam detection API says so).
  ok    — saved to the inbox.

The spam detection API (settings.SPAM_DETECTION_URL) is best-effort: if it is
slow or down, the message goes to the inbox rather than being lost.
"""
import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMESTAMP_SALT = "legal.contact.rendered-at"
MIN_SECONDS = 3            # humans can't fill the form faster than this
MAX_PER_HOUR = 5           # messages per IP address
MAX_LINKS = 2              # more than this and it's filed as spam
API_TIMEOUT = 4            # seconds
BULK_SIZE = 100            # the API's per-request item cap

LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


@dataclass
class Verdict:
    action: str                 # "drop" | "limit" | "spam" | "ok"
    reason: str = ""            # ContactMessage.spam_reason for "spam"
    score: float | None = None  # spam detection API score, when it answered


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


def _post(path: str, payload: dict) -> dict | None:
    base = getattr(settings, "SPAM_DETECTION_URL", "")
    if not base:
        return None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = getattr(settings, "SPAM_DETECTION_API_KEY", "")
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception:  # network, HTTP error, bad JSON: never block the form
        logger.warning("Spam detection API call to %s failed", path, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def screen(request, data: dict, trap: str, rendered_at: str) -> Verdict:
    """Run every check, cheapest first. ``data`` is the form's cleaned_data."""
    from apps.legal.models import ContactMessage

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

    text = f"{data.get('subject', '')} {data.get('message', '')}"
    if len(LINK_RE.findall(text)) > MAX_LINKS:
        return Verdict("spam", reason="links")

    result = _post("/v2/check-spam/", {
        "text": data["message"],
        "subject": data.get("subject", ""),
        "name": data.get("name", ""),
        "email": data.get("email", ""),
    })
    if not result or not result.get("success"):
        return Verdict("ok")
    score = result.get("spam_score")
    if result.get("is_spam"):
        return Verdict("spam", reason="detector", score=score)
    return Verdict("ok", score=score)


def report(messages, is_spam: bool) -> None:
    """
    Tell the spam detection API the owner's verdict on these messages, so its
    model learns from both mistakes and confirmations.
    """
    items = [
        {"message": m.message[:10000], "subject": m.subject[:500], "is_spam": is_spam}
        for m in messages if m.message.strip()
    ]
    for start in range(0, len(items), BULK_SIZE):
        _post("/v2/suggestion/bulk/", {"items": items[start:start + BULK_SIZE]})
