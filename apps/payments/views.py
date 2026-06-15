"""
Payment views — pure HTTP layer.

Each view does one thing: validate, call service, return response.
Zero business logic.  Zero ORM calls.  Zero Stripe imports.
"""
import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.booking.models import SessionPricing
from apps.payments.interfaces import WebhookSignatureError
from apps.payments.services import cart as cart_svc
from apps.payments.services.checkout import (
    cancel_pending_order,
    confirm_from_session_id,
    confirm_order,
    create_checkout_session,
    create_order_from_cart,
)
from apps.payments.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cart (HTMX partials)
# ---------------------------------------------------------------------------

@require_POST
def cart_add(request: HttpRequest) -> HttpResponse:
    """Add a booking slot to the cart.  Returns the cart drawer partial."""
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST

    session_type_id = int(data["session_type_id"])
    location_id = int(data["location_id"])

    # Look up the price server-side — never trust client-supplied price_pence.
    try:
        pricing = SessionPricing.objects.get(
            session_type_id=session_type_id,
            location_id=location_id,
        )
    except SessionPricing.DoesNotExist:
        return HttpResponse("Invalid session or location.", status=400)

    cart_svc.add_to_cart(
        request,
        session_type_id=session_type_id,
        location_id=location_id,
        date_str=data["date"],
        start_time=data["start_time"],
        end_time=data["end_time"],
        price_pence=pricing.price_pence,
        label=data.get("label", "Session"),
    )
    return _cart_response(request)


@require_POST
def cart_add_product(request: HttpRequest) -> HttpResponse:
    """Add a product to the cart.  Returns the cart drawer partial."""
    from apps.shop.models import Product

    data = json.loads(request.body) if request.content_type == "application/json" else request.POST

    product_id = int(data["product_id"])

    # Look up the canonical price server-side — never trust client-supplied value.
    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        return HttpResponse("Product not found.", status=400)

    cart_svc.add_product_to_cart(
        request,
        product_id=product_id,
        name=product.name,
        color=data.get("color", ""),
        price_pence=product.price_pence,
        qty=int(data.get("qty", 1)),
        photo_class=data.get("photo_class", ""),
        image_url=data.get("image_url", ""),
    )
    return _cart_response(request)


@require_POST
def cart_update_qty(request: HttpRequest) -> HttpResponse:
    """Update product quantity.  Returns the cart drawer partial."""
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    product_id = int(data["product_id"])
    qty = int(data["qty"])
    cart_svc.update_product_qty(request, product_id, qty)
    return _cart_response(request)


@require_POST
def cart_remove(request: HttpRequest) -> HttpResponse:
    """Remove an item by index."""
    index = int(request.POST.get("index", -1))
    cart_svc.remove_from_cart(request, index)
    return _cart_response(request)


@require_POST
def cart_clear(request: HttpRequest) -> HttpResponse:
    cart_svc.clear_cart(request)
    return _cart_response(request)


@require_POST
def cart_apply_voucher(request: HttpRequest) -> HttpResponse:
    """Apply a voucher code."""
    code = request.POST.get("code", "")
    try:
        cart_svc.apply_voucher(request, code)
    except ValueError as exc:
        return render(request, "payments/partials/cart_drawer.html", {
            "cart": cart_svc.get_cart(request),
            "cart_total": cart_svc.cart_total_pence(request),
            "voucher_code": code,
            "voucher_error": str(exc),
        })
    return _cart_response(request)


@require_POST
def cart_remove_voucher(request: HttpRequest) -> HttpResponse:
    cart_svc.clear_voucher(request)
    return _cart_response(request)


def cart_view(request: HttpRequest) -> HttpResponse:
    """Return the full cart drawer contents (GET)."""
    return _cart_response(request)


def cart_badge(request: HttpRequest) -> HttpResponse:
    """Return just the badge count (HTMX swap target)."""
    count = cart_svc.cart_count(request)
    return render(request, "payments/partials/cart_badge.html", {"cart_count": count})


def _cart_response(request: HttpRequest) -> HttpResponse:
    """Render the full cart drawer partial."""
    cart = cart_svc.get_cart(request)
    subtotal = cart_svc.cart_total_pence(request)
    voucher_code, discount = cart_svc.get_voucher_discount(request)

    # Shipping (only applies when there are physical products)
    shipping = 0
    show_shipping = cart_svc.has_products(request)
    if show_shipping:
        from apps.shop.models import ShopSettings
        shop = ShopSettings.load()
        shipping = shop.shipping_cost(cart_svc.product_total_pence(request))

    total = max(0, subtotal + shipping - discount)

    return render(request, "payments/partials/cart_drawer.html", {
        "cart": cart,
        "cart_count": cart_svc.cart_count(request),
        "cart_subtotal": subtotal,
        "voucher_code": voucher_code,
        "voucher_discount": discount,
        "shipping_pence": shipping,
        "show_shipping": show_shipping,
        "cart_total": total,
    })


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

@require_POST
def checkout(request: HttpRequest) -> HttpResponse:
    """Create Order from cart, redirect to Stripe."""
    name = request.POST.get("client_name", "").strip()
    email = request.POST.get("client_email", "").strip()
    phone = request.POST.get("client_phone", "").strip()

    terms_accepted = request.POST.get("terms_accepted")

    if not name or not email:
        return render(request, "payments/checkout.html", {
            "error": "Name and email are required.",
            "cart": cart_svc.get_cart(request),
            "cart_total": cart_svc.cart_total_pence(request),
        })

    if not terms_accepted:
        return render(request, "payments/checkout.html", {
            "error": "You must accept the Terms & Conditions to proceed.",
            "cart": cart_svc.get_cart(request),
            "cart_total": cart_svc.cart_total_pence(request),
        })

    try:
        order = create_order_from_cart(request, name, email, phone)
    except ValueError as exc:
        return render(request, "payments/checkout.html", {
            "error": str(exc),
            "cart": cart_svc.get_cart(request),
            "cart_total": cart_svc.cart_total_pence(request),
        })

    # Store so the cancel page can release pending bookings if the user bails.
    request.session["pending_order_ref"] = str(order.reference)

    session = create_checkout_session(request, order)
    return redirect(session.redirect_url, permanent=False)


def checkout_page(request: HttpRequest) -> HttpResponse:
    """Show the checkout form (GET)."""
    cart = cart_svc.get_cart(request)
    if not cart:
        return redirect("booking:page")

    subtotal = cart_svc.cart_total_pence(request)
    voucher_code, discount = cart_svc.get_voucher_discount(request)

    shipping = 0
    show_shipping = cart_svc.has_products(request)
    if show_shipping:
        from apps.shop.models import ShopSettings
        shop = ShopSettings.load()
        shipping = shop.shipping_cost(cart_svc.product_total_pence(request))

    total = max(0, subtotal + shipping - discount)

    return render(request, "payments/checkout.html", {
        "cart": cart,
        "cart_subtotal": subtotal,
        "voucher_code": voucher_code,
        "voucher_discount": discount,
        "shipping_pence": shipping,
        "show_shipping": show_shipping,
        "cart_total": total,
    })


# ---------------------------------------------------------------------------
# Success / Cancel
# ---------------------------------------------------------------------------

def payment_success(request: HttpRequest) -> HttpResponse:
    """
    Stripe redirects here after checkout.
    Also acts as webhook fallback — confirms via session_id if webhook
    hasn't fired yet.
    """
    session_id = request.GET.get("session_id", "")
    order = confirm_from_session_id(session_id)

    order_type = "booking"  # default
    if order:
        item_types = set(order.items.values_list("item_type", flat=True))
        if item_types == {"product"}:
            order_type = "product"
        elif "booking" in item_types and "product" in item_types:
            order_type = "mixed"

    return render(request, "payments/success.html", {
        "order": order,
        "order_type": order_type,
    })


def payment_cancel(request: HttpRequest) -> HttpResponse:
    order_ref = request.session.pop("pending_order_ref", None)
    if order_ref:
        cancel_pending_order(order_ref)
    return render(request, "payments/cancel.html")


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """
    Receive Stripe webhook events.
    400 = bad signature.  200 = everything else.
    """
    try:
        event = StripeService().parse_webhook(request.body, request.META)
    except WebhookSignatureError:
        return HttpResponse(status=400)

    if event is not None:
        confirm_order(event)

    return HttpResponse(status=200)
