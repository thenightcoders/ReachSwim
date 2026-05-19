from django.urls import path
from . import views

app_name = "booking"

urlpatterns = [
    # Full page
    path("book/", views.booking_page, name="page"),

    # HTMX partials
    path(
        "book/calendar/<int:session_type_id>/",
        views.htmx_calendar_panel,
        name="htmx_calendar",
    ),
    path(
        "book/slots/<int:session_type_id>/<int:location_id>/",
        views.htmx_slots,
        name="htmx_slots",
    ),
]
