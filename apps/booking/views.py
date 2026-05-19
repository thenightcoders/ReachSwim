import calendar
import datetime

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET

from .models import BookingSettings, SessionType, Location, SessionPricing
from .services.availability import (
    get_available_dates,
    get_slots_for_date,
)


# =============================================================================
# Main booking page
# =============================================================================

def booking_page(request):
    """Full page — session type selector + calendar panel."""
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
def htmx_calendar_panel(request, session_type_id):
    """
    Return the full Calendly-style panel: location dropdown + month calendar.
    Query params: ?location_id=N&year=YYYY&month=MM
    """
    session_type = get_object_or_404(SessionType, pk=session_type_id, is_active=True)

    # All locations with pricing for this session type
    location_ids = session_type.pricing.values_list("location_id", flat=True)
    locations = Location.objects.filter(pk__in=location_ids, is_active=True)

    if not locations.exists():
        return HttpResponse('<p class="booking-empty">No locations available.</p>')

    # Selected location (default to first)
    loc_id = request.GET.get("location_id")
    if loc_id:
        location = get_object_or_404(Location, pk=loc_id, is_active=True)
    else:
        location = locations.first()

    # Price for this combo
    try:
        pricing = SessionPricing.objects.get(
            session_type=session_type, location=location,
        )
        price_pence = pricing.price_pence
    except SessionPricing.DoesNotExist:
        price_pence = 0

    # Which month to show
    today = datetime.date.today()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        # Clamp
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    # Available dates for this session_type + location
    available_dates = set(get_available_dates(session_type, location))

    # Build calendar grid (list of weeks, each week = 7 day-dicts)
    cal = calendar.Calendar(firstweekday=0)  # Monday first
    weeks = []
    for dt in cal.itermonthdates(year, month):
        if not weeks or len(weeks[-1]) == 7:
            weeks.append([])
        in_month = dt.month == month
        is_past = dt <= today
        is_available = dt in available_dates
        weeks[-1].append({
            "date": dt,
            "in_month": in_month,
            "is_past": is_past,
            "is_available": in_month and not is_past and is_available,
            "is_today": dt == today,
        })

    # Prev / next month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # Don't allow navigating before current month
    show_prev = (prev_year, prev_month) >= (today.year, today.month)

    # Don't allow navigating beyond booking window
    bs = BookingSettings.load()
    max_date = today + datetime.timedelta(days=bs.max_advance_days)
    show_next = datetime.date(next_year, next_month, 1) <= max_date

    month_label = datetime.date(year, month, 1).strftime("%B %Y")

    return render(request, "booking/partials/calendar_panel.html", {
        "session_type": session_type,
        "locations": locations,
        "location": location,
        "price_pence": price_pence,
        "weeks": weeks,
        "month_label": month_label,
        "year": year,
        "month": month,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "show_prev": show_prev,
        "show_next": show_next,
        "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
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
