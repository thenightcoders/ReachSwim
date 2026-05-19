import datetime

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET

from .models import BookingSettings, SessionType, Location
from .services.availability import (
    get_available_dates,
    get_slots_for_date,
)


# =============================================================================
# Main booking page
# =============================================================================

def booking_page(request):
    """Full page — session type selector + empty HTMX targets."""
    settings = BookingSettings.load()
    session_types = SessionType.objects.filter(is_active=True)

    return render(request, "booking/booking.html", {
        "settings": settings,
        "session_types": session_types,
    })


# =============================================================================
# HTMX partials
# =============================================================================

@require_GET
def htmx_locations(request, session_type_id):
    """Return location buttons for a given session type."""
    session_type = get_object_or_404(SessionType, pk=session_type_id, is_active=True)

    # Only locations that have pricing set for this session type
    location_ids = session_type.pricing.values_list("location_id", flat=True)
    locations = Location.objects.filter(
        pk__in=location_ids,
        is_active=True,
    )

    return render(request, "booking/partials/locations.html", {
        "session_type": session_type,
        "locations": locations,
    })


@require_GET
def htmx_dates(request, session_type_id, location_id):
    """Return available dates for a session type + location."""
    session_type = get_object_or_404(SessionType, pk=session_type_id, is_active=True)
    location = get_object_or_404(Location, pk=location_id, is_active=True)

    dates = get_available_dates(session_type, location)

    return render(request, "booking/partials/dates.html", {
        "session_type": session_type,
        "location": location,
        "dates": dates,
    })


@require_GET
def htmx_slots(request, session_type_id, location_id):
    """Return time slots for a specific date."""
    session_type = get_object_or_404(SessionType, pk=session_type_id, is_active=True)
    location = get_object_or_404(Location, pk=location_id, is_active=True)

    date_str = request.GET.get("date")
    if not date_str:
        return HttpResponse("")

    try:
        date = datetime.date.fromisoformat(date_str)
    except ValueError:
        return HttpResponse("")

    slots = get_slots_for_date(session_type, location, date)

    return render(request, "booking/partials/slots.html", {
        "session_type": session_type,
        "location": location,
        "date": date,
        "slots": slots,
    })
