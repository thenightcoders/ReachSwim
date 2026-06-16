"""
Package listing and add-to-cart views.

One responsibility: HTTP layer for the package purchase flow.
No business logic — delegates to cart service.
"""
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.booking.models import Package, SessionType
from apps.payments.services import cart as cart_svc


def packages_page(request):
    """List active packages, grouped by session type."""
    session_types = (
        SessionType.objects
        .filter(is_active=True, packages__is_active=True)
        .prefetch_related(
            Prefetch(
                "packages",
                queryset=Package.objects.filter(is_active=True)
                    .select_related("location")
                    .order_by("order", "price_pence"),
                to_attr="active_packages",
            )
        )
        .distinct()
    )
    return render(request, "booking/packages.html", {"session_types": session_types})


@require_POST
def package_add_to_cart(request, package_id: int):
    """Add a package to the cart and return the cart drawer partial."""
    from apps.payments.views import _cart_response  # shared helper

    package = get_object_or_404(Package, pk=package_id, is_active=True)

    cart_svc.add_package_to_cart(
        request,
        package_id=package.pk,
        name=package.name,
        price_pence=package.price_pence,
        label=f"{package.name} ({package.session_count} sessions @ {package.location.name})",
    )
    return _cart_response(request)
