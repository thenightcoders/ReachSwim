"""
Google Calendar service — stubs for OAuth2 flow and event CRUD.

The owner connects their personal Gmail calendar via OAuth2.
Confirmed bookings are written as calendar events; cancellations delete them.
Blocked-off times on the calendar reduce available slots.

Implementation requires:
  pip install google-auth google-auth-oauthlib google-api-python-client

Wired up when we have real credentials and the accounts app for the admin flow.
"""
from typing import Optional

from apps.booking.models import Booking, GoogleCalendarConfig


# ---------------------------------------------------------------------------
# OAuth2 flow  (admin connects their Google account)
# ---------------------------------------------------------------------------

def get_auth_url() -> str:
    """Generate the Google OAuth2 consent URL for the owner."""
    # TODO: build OAuth2 flow with google-auth-oauthlib
    raise NotImplementedError("Google Calendar OAuth not yet configured.")


def handle_oauth_callback(code: str) -> None:
    """Exchange the authorization code for tokens, store in GoogleCalendarConfig."""
    # TODO: exchange code, store refresh token in GoogleCalendarConfig.credentials_json
    raise NotImplementedError("Google Calendar OAuth not yet configured.")


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

def create_event(booking: Booking) -> Optional[str]:
    """
    Create a Google Calendar event for a confirmed booking.
    Returns the event ID or None if calendar is not connected.
    """
    config = GoogleCalendarConfig.load()
    if not config.is_connected:
        return None

    # TODO: build event dict, call calendar API, return event_id
    # event = {
    #     "summary": f"{booking.session_type.name} — {booking.client_name}",
    #     "location": booking.location.address,
    #     "start": {"dateTime": ..., "timeZone": "Europe/London"},
    #     "end": {"dateTime": ..., "timeZone": "Europe/London"},
    #     "description": f"Client: {booking.client_name}\nEmail: {booking.client_email}",
    # }
    raise NotImplementedError("Google Calendar API not yet configured.")


def delete_event(booking: Booking) -> None:
    """Delete the Google Calendar event for a cancelled booking."""
    config = GoogleCalendarConfig.load()
    if not config.is_connected or not booking.google_event_id:
        return

    # TODO: call calendar API to delete event
    raise NotImplementedError("Google Calendar API not yet configured.")


def get_busy_times(date):
    """
    Fetch busy/blocked times from the owner's calendar for a given date.
    Used by the availability service to exclude times the coach is unavailable.
    """
    config = GoogleCalendarConfig.load()
    if not config.is_connected:
        return []

    # TODO: call freebusy API
    raise NotImplementedError("Google Calendar API not yet configured.")
