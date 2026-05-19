from django.urls import path
from . import views

app_name = "booking"

urlpatterns = [
    # Full page
    path("book/", views.booking_page, name="page"),

    # HTMX partials
    path(
        "book/locations/<int:session_type_id>/",
        views.htmx_locations,
        name="htmx_locations",
    ),
    path(
        "book/dates/<int:session_type_id>/<int:location_id>/",
        views.htmx_dates,
        name="htmx_dates",
    ),
    path(
        "book/slots/<int:session_type_id>/<int:location_id>/",
        views.htmx_slots,
        name="htmx_slots",
    ),
]
