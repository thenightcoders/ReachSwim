from django.urls import path
from django.views.generic import RedirectView
from . import views, views_packages

app_name = "booking"

urlpatterns = [
    # Redirect legacy /booking/ to canonical /book/
    path("booking/", RedirectView.as_view(url="/book/", permanent=True), name="page_redirect"),

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

    # Packages
    path("packages/", views_packages.packages_page, name="packages"),
    path("packages/<int:package_id>/add/", views_packages.package_add_to_cart, name="package_add"),
]
