"""
Google Calendar service — OAuth2 flow, event CRUD, freebusy.

Requires:
    google-auth google-auth-oauthlib google-api-python-client

Owner connects via /dashboard/google-calendar/connect/.
Confirmed bookings create events; cancellations delete them.
Freebusy API blocks slots the owner has already reserved in their calendar.
"""
import datetime
import json
import logging
from typing import List, Optional, Tuple

from django.utils import timezone

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_config():
    from apps.booking.models import GoogleCalendarConfig
    return GoogleCalendarConfig.load()


def _flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    config = _load_config()
    client_config = {
        "web": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def _get_credentials():
    """Return valid Credentials, refreshing the access token if expired."""
    import google.oauth2.credentials
    from google.auth.transport.requests import Request

    config = _load_config()
    if not config.is_connected or not config.credentials_json:
        return None

    data = json.loads(config.credentials_json)
    creds = google.oauth2.credentials.Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", TOKEN_URI),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            data["token"] = creds.token
            config.credentials_json = json.dumps(data)
            config.save(update_fields=["credentials_json"])
        except Exception as exc:
            logger.error("Token refresh failed: %s", exc)
            return None

    return creds


def _service():
    from googleapiclient.discovery import build

    creds = _get_credentials()
    if creds is None:
        return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# OAuth2 flow
# ---------------------------------------------------------------------------

def get_auth_url(redirect_uri: str) -> tuple:
    """
    Build the Google consent URL.
    Returns (auth_url, code_verifier) — store code_verifier in the session
    and pass it back to handle_oauth_callback.
    """
    flow = _flow(redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",   # always return a refresh token
    )
    return auth_url, flow.code_verifier


def handle_oauth_callback(code: str, redirect_uri: str, code_verifier: str = None) -> None:
    """Exchange auth code for tokens; persist in GoogleCalendarConfig."""
    flow = _flow(redirect_uri)
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials

    config = _load_config()
    config.credentials_json = json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    })
    if not config.calendar_id:
        config.calendar_id = "primary"
    config.is_connected = True
    config.last_synced = timezone.now()
    config.save()


def disconnect() -> None:
    """Wipe stored tokens and mark as disconnected."""
    config = _load_config()
    config.credentials_json = ""
    config.is_connected = False
    config.last_synced = None
    config.save(update_fields=["credentials_json", "is_connected", "last_synced"])


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

def create_event(booking) -> Optional[str]:
    """
    Create a calendar event for a confirmed booking.
    Returns the Google event ID (stored on the booking), or None on failure.
    """
    config = _load_config()
    if not config.is_connected:
        return None

    svc = _service()
    if svc is None:
        return None

    try:
        start_dt = datetime.datetime.combine(booking.date, booking.start_time)
        end_dt = datetime.datetime.combine(booking.date, booking.end_time)

        event = {
            "summary": f"{booking.session_type.name} — {booking.client_name}",
            "location": getattr(booking.location, "address", ""),
            "description": (
                f"Client: {booking.client_name}\n"
                f"Email: {booking.client_email}\n"
                f"Phone: {booking.client_phone}\n"
                f"Notes: {booking.notes}"
            ).strip(),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/London"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Europe/London"},
            # Mark as a ReachSwim booking so get_busy_times can skip it.
            # Slot capacity is tracked in the DB; these events must not
            # be treated as owner-blocked time.
            "extendedProperties": {
                "private": {
                    "reachswim_booking": "true",
                    "booking_id": str(booking.pk),
                }
            },
        }

        created = svc.events().insert(
            calendarId=config.calendar_id or "primary",
            body=event,
        ).execute()

        config.last_synced = timezone.now()
        config.save(update_fields=["last_synced"])

        return created.get("id")

    except Exception as exc:
        logger.error("create_event failed for booking %s: %s", booking.pk, exc)
        return None


def delete_event(booking) -> None:
    """Delete the calendar event for a cancelled booking."""
    config = _load_config()
    if not config.is_connected or not booking.google_event_id:
        return

    svc = _service()
    if svc is None:
        return

    try:
        svc.events().delete(
            calendarId=config.calendar_id or "primary",
            eventId=booking.google_event_id,
        ).execute()
        config.last_synced = timezone.now()
        config.save(update_fields=["last_synced"])
    except Exception as exc:
        logger.error("delete_event failed for booking %s: %s", booking.pk, exc)


# ---------------------------------------------------------------------------
# Freebusy (two-way sync — blocks slots the owner reserved themselves)
# ---------------------------------------------------------------------------

def get_busy_times(date: datetime.date) -> List[Tuple[datetime.time, datetime.time]]:
    """
    Return (start_time, end_time) pairs for periods the owner has personally
    blocked on `date` (holidays, personal appointments, etc.).

    Events created by ReachSwim (tagged with the 'reachswim_booking' extended
    property) are intentionally skipped — their capacity is already tracked in
    the database via Booking.count_for_slot, so they must not also block the
    slot as owner-unavailable time.
    """
    config = _load_config()
    if not config.is_connected:
        return []

    svc = _service()
    if svc is None:
        return []

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("Europe/London")

        day_start = datetime.datetime.combine(date, datetime.time.min).replace(tzinfo=tz)
        day_end   = datetime.datetime.combine(date, datetime.time.max).replace(tzinfo=tz)

        result = svc.events().list(
            calendarId=config.calendar_id or "primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        out = []
        for event in result.get("items", []):
            # Skip events this app created — they are not owner-blocked time.
            private_props = event.get("extendedProperties", {}).get("private", {})
            if private_props.get("reachswim_booking") == "true":
                continue

            start_str = event.get("start", {}).get("dateTime")
            end_str   = event.get("end",   {}).get("dateTime")
            if not start_str or not end_str:
                continue  # all-day event, skip

            start = datetime.datetime.fromisoformat(start_str)
            end   = datetime.datetime.fromisoformat(end_str)
            start_local = start.astimezone(tz).time().replace(tzinfo=None)
            end_local   = end.astimezone(tz).time().replace(tzinfo=None)
            out.append((start_local, end_local))

        return out

    except Exception as exc:
        logger.error("get_busy_times failed for %s: %s", date, exc)
        return []
