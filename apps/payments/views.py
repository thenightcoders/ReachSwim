"""
Payment views — pure HTTP layer.

Each view does one thing: validate, call service, return response.
Zero business logic.  Zero ORM calls.  Zero Stripe imports.
"""
import json
import logging
from typing import Optional

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.booking.models import SessionPricing
from apps.payments.interfaces import WebhookSignatureError
from apps.payments.models import Order
from apps.payments.services import cart as cart_svc
from apps.payments.services.cart import ITEM_TYPE_BOOKING, VOUCHER_SESSION_KEY, CREDITS_SESSION_KEY
from apps.booking.services.booking import SlotUnavailableError
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
    """
    Add a booking slot to the cart.

    Creates a pending Booking immediately so the slot count decrements in the
    DB right away — not only at checkout.  Returns the cart drawer partial.
    """
    import datetime as _dt
    from apps.booking.services.booking import create_booking

    data = json.loads(request.body) if request.content_type == "application/json" else request.POST

    session_type_id = int(data["session_type_id"])
    location_id = int(data["location_id"])
    date_str = data["date"]
    start_time_str = data["start_time"]
    end_time_str = data["end_time"]

    # Look up the price server-side — never trust client-supplied price_pence.
    try:
        pricing = SessionPricing.objects.get(
            session_type_id=session_type_id,
            location_id=location_id,
        )
    except SessionPricing.DoesNotExist:
        return HttpResponse("Invalid session or location.", status=400)

    # Duplicate guard — if this exact slot is already in the cart, no-op.
    target_key = (
        cart_svc.ITEM_TYPE_BOOKING,
        session_type_id,
        location_id,
        date_str,
        start_time_str,
    )
    for existing in cart_svc.get_cart(request):
        if cart_svc._cart_key(existing) == target_key:
            return _cart_response(request)

    # Reserve the slot in the DB now.  Uses select_for_update so concurrent
    # requests queue up; second one gets SlotUnavailableError.
    client_name = "Guest"
    client_email = "pending@reachswim.com"
    authed_user = None
    if hasattr(request, "user") and request.user.is_authenticated:
        authed_user = request.user
        client_name = getattr(request.user, "full_name", None) or request.user.email
        client_email = request.user.email

    try:
        booking = create_booking(
            session_type_id=session_type_id,
            location_id=location_id,
            date=_dt.date.fromisoformat(date_str),
            start_time=_dt.time.fromisoformat(start_time_str),
            client_name=client_name,
            client_email=client_email,
            user=authed_user,
        )
    except SlotUnavailableError as exc:
        return _cart_response(request, error=str(exc))

    cart_svc.add_to_cart(
        request,
        session_type_id=session_type_id,
        location_id=location_id,
        date_str=date_str,
        start_time=start_time_str,
        end_time=end_time_str,
        price_pence=pricing.price_pence,
        label=data.get("label", "Session"),
        booking_id=booking.id,
        reserved_at=_dt.datetime.now().timestamp(),
    )
    cart_svc.auto_apply_credit_for_booking(
        request,
        session_type_id=session_type_id,
        location_id=location_id,
        price_pence=pricing.price_pence,
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
    """Remove an item by index.  Cancels any pending DB booking for that slot."""
    index = int(request.POST.get("index", -1))
    cart = cart_svc.get_cart(request)
    if 0 <= index < len(cart):
        _cancel_cart_booking(cart[index].get("booking_id"))
    cart_svc.remove_from_cart(request, index)
    return _cart_response(request)


@require_POST
def cart_clear(request: HttpRequest) -> HttpResponse:
    """Clear the cart, cancelling all pending DB bookings first."""
    for item in cart_svc.get_cart(request):
        _cancel_cart_booking(item.get("booking_id"))
    cart_svc.clear_cart(request)
    return _cart_response(request)


@require_POST
def cart_apply_voucher(request: HttpRequest) -> HttpResponse:
    """Apply a voucher code (rate-limited: 5 attempts/min per IP)."""
    from apps.payments.services.rate_limiter import is_allowed

    ip = request.META.get("REMOTE_ADDR", "unknown")
    if not is_allowed(f"voucher:{ip}"):
        return render(request, "payments/partials/cart_drawer.html", {
            **_cart_context(request),
            "voucher_error": "Too many attempts — please wait a minute and try again.",
        })

    code = request.POST.get("code", "")
    try:
        cart_svc.apply_voucher(request, code)
    except ValueError as exc:
        return render(request, "payments/partials/cart_drawer.html", {
            **_cart_context(request),
            "voucher_error": str(exc),
        })
    return _cart_response(request)


@require_POST
def cart_remove_voucher(request: HttpRequest) -> HttpResponse:
    cart_svc.clear_voucher(request)
    return _cart_response(request)


@require_POST
def cart_remove_credit(request: HttpRequest) -> HttpResponse:
    """Remove one auto-applied package credit by its voucher code."""
    code = request.POST.get("code", "").strip().upper()
    if code:
        cart_svc.remove_credit(request, code)
    return _cart_response(request)


def cart_view(request: HttpRequest) -> HttpResponse:
    """Return the full cart drawer contents (GET)."""
    return _cart_response(request)


def cart_badge(request: HttpRequest) -> HttpResponse:
    """Return just the badge count (HTMX swap target)."""
    count = cart_svc.cart_count(request)
    return render(request, "payments/partials/cart_badge.html", {"cart_count": count})


def _cart_context(request: HttpRequest) -> dict:
    """Build the shared context dict for the cart drawer."""
    # Expire stale cart reservations before computing the cart state.
    expired_labels = cart_svc.check_and_expire_reservations(request)
    cart = cart_svc.get_cart(request)
    subtotal = cart_svc.cart_total_pence(request)
    voucher_code, voucher_discount = cart_svc.get_voucher_discount(request)
    credits = cart_svc.get_credits(request)
    credits_total = cart_svc.get_credits_total(request)
    total_discount = voucher_discount + credits_total

    shipping = 0
    show_shipping = cart_svc.has_products(request)
    if show_shipping:
        from apps.shop.models import ShopSettings
        shop = ShopSettings.load()
        shipping = shop.shipping_cost(cart_svc.product_total_pence(request))

    total = max(0, subtotal + shipping - total_discount)

    # Hint only shown when the user has credits but none matched the cart yet.
    has_any_discount = voucher_code or credits
    package_credits_hint = None if has_any_discount else _package_credits_hint(request, cart)

    return {
        "cart": cart,
        "cart_count": cart_svc.cart_count(request),
        "cart_subtotal": subtotal,
        "voucher_code": voucher_code,
        "voucher_discount": voucher_discount,
        "credits": credits,
        "credits_total": credits_total,
        "shipping_pence": shipping,
        "show_shipping": show_shipping,
        "cart_total": total,
        "package_credits_hint": package_credits_hint,
        "reservation_expired": expired_labels,  # slots removed due to 5-min TTL
    }


def _package_credits_hint(request: HttpRequest, cart: list) -> str | None:
    """
    Return a hint string if the logged-in user has active package session credits
    that cover one or more booking items in the cart.  Returns None otherwise.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None

    has_booking = any(i.get("item_type") == ITEM_TYPE_BOOKING for i in cart)
    if not has_booking:
        return None

    from apps.payments.models import PackagePurchase
    from django.db.models import Count, Q

    total = (
        PackagePurchase.objects
        .filter(user=request.user)
        .aggregate(
            n=Count("vouchers", filter=Q(vouchers__times_used=0, vouchers__is_active=True))
        )["n"] or 0
    )

    if not total:
        return None

    word = "credit" if total == 1 else "credits"
    return f"You have {total} session {word} — they'll be applied automatically at checkout."


def _cancel_cart_booking(booking_id: Optional[int]) -> None:
    """
    Cancel a pending Booking that was reserved at cart-add time.
    Safe to call with None or an already-cancelled booking — both no-op.
    """
    if not booking_id:
        return
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking
    try:
        bk = Booking.objects.get(pk=booking_id, status=Booking.STATUS_PENDING)
        cancel_booking(bk, notify_client=False)
    except Booking.DoesNotExist:
        pass  # already cancelled or confirmed — nothing to do


def _cart_response(request: HttpRequest, error: str = "") -> HttpResponse:
    """Render the full cart drawer partial."""
    ctx = _cart_context(request)
    if error:
        ctx["cart_add_error"] = error
    response = render(request, "payments/partials/cart_drawer.html", ctx)
    if error:
        response["X-Cart-Error"] = "true"
    return response


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
    use_credit = request.POST.get("use_credit")

    # Fallback: credits are applied per booking_add, so by checkout they're
    # usually already in session.  The use_credit checkbox is kept for the
    # edge case where the session was cleared after the cart was built.
    # (No action needed — credits live in CREDITS_SESSION_KEY, not here.)

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
    except SlotUnavailableError as exc:
        return render(request, "payments/checkout.html", {
            "error": str(exc),
            "cart": cart_svc.get_cart(request),
            "cart_total": cart_svc.cart_total_pence(request),
        })
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


def _find_auto_credit(user, cart):
    """
    Return (first_matching_voucher, total_credit_count) for a logged-in user.
    Looks for unused, active, in-date credits that match the booking in the cart.
    Returns (None, 0) if the user has no applicable credits.
    """
    from apps.payments.models import Voucher
    from django.utils import timezone

    if not getattr(user, "is_authenticated", False):
        return None, 0

    booking = next((i for i in cart if i.get("item_type") == ITEM_TYPE_BOOKING), None)
    if not booking:
        return None, 0

    now = timezone.now()
    qs = Voucher.objects.filter(
        package_purchase__user=user,
        session_type_id=booking["session_type_id"],
        location_id=booking["location_id"],
        times_used=0,
        is_active=True,
        valid_from__lte=now,
        valid_until__gte=now,
    )
    count = qs.count()
    if count == 0:
        return None, 0
    return qs.first(), count


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

    # Auto-credit offer: detect if the logged-in user has applicable credits.
    # Only shown when no voucher is already applied in the session.
    auto_credit_voucher, auto_credit_count = (None, 0)
    if not voucher_code:
        auto_credit_voucher, auto_credit_count = _find_auto_credit(
            getattr(request, "user", None), cart
        )

    return render(request, "payments/checkout.html", {
        "cart": cart,
        "cart_subtotal": subtotal,
        "voucher_code": voucher_code,
        "voucher_discount": discount,
        "shipping_pence": shipping,
        "show_shipping": show_shipping,
        "cart_total": total,
        "auto_credit_count": auto_credit_count,
        # For DISCOUNT_FULL credits, savings = one booking's price (not whole
        # cart subtotal).  _find_auto_credit returns the first matching booking
        # as context via the cart, so look it up from the cart directly.
        "auto_credit_savings": (
            next(
                (i["price_pence"] for i in cart if i.get("item_type") == ITEM_TYPE_BOOKING),
                0,
            )
            if auto_credit_voucher and auto_credit_voucher.discount_type == "full"
            else (auto_credit_voucher.calculate_discount(subtotal) if auto_credit_voucher else 0)
        ),
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
    400 = bad signature.  200 = everything else (Stripe retries on non-2xx).

    Handled event types:
      checkout.session.completed → confirm_order()
      charge.refund.updated      → _handle_refund_update()
    """
    try:
        event = StripeService().parse_webhook(request.body, request.META)
    except WebhookSignatureError:
        return HttpResponse(status=400)

    if event is not None:
        confirm_order(event)

    # parse_webhook() returns None for every unhandled event type (signature
    # was valid).  Route any additional event types we care about here.
    try:
        raw = json.loads(request.body)
        if raw.get("type") == "charge.refund.updated":
            _handle_refund_update(raw)
    except Exception:
        logger.exception("Error routing secondary webhook event")

    return HttpResponse(status=200)


def _handle_refund_update(raw_event: dict) -> None:
    """
    Handle charge.refund.updated — fired when an async Stripe refund
    (e.g. ACH) transitions from pending to succeeded or failed.

    Updates the Refund record status.  On succeeded, applies side effects
    (booking cancellation / stock restock) and flips the order status.
    """
    from apps.payments.models import Refund
    from apps.payments.services.refund import apply_refund_succeeded

    try:
        refund_data = raw_event["data"]["object"]
        stripe_refund_id = refund_data["id"]
        new_status       = refund_data["status"]
    except (KeyError, TypeError):
        logger.warning("charge.refund.updated: unexpected payload shape — ignoring.")
        return

    try:
        refund = Refund.objects.select_related("order", "order_item").get(
            stripe_refund_id=stripe_refund_id
        )
    except Refund.DoesNotExist:
        # Refund issued outside the dashboard (e.g. Stripe dashboard) — ignore.
        logger.info(
            "charge.refund.updated: no local Refund record for %s — ignoring.",
            stripe_refund_id,
        )
        return

    if refund.status == new_status:
        return  # idempotent — already up to date

    if new_status == "succeeded":
        apply_refund_succeeded(refund)
    else:
        # pending → failed, or any other transition: just update the status.
        Refund.objects.filter(pk=refund.pk).update(status=new_status)
        logger.info(
            "Refund %s status updated via webhook: %s → %s",
            stripe_refund_id, refund.status, new_status,
        )


# ---------------------------------------------------------------------------
# Payment reminder resume  (client clicks link from reminder email)
# ---------------------------------------------------------------------------

def resume_payment(request: HttpRequest, token: str) -> HttpResponse:
    """
    Decode a signed payment-reminder token, create a fresh Stripe Checkout
    session for the associated Order, and redirect the client to Stripe.

    GET /pay/resume/<token>/

    The token encodes the Order reference and expires after REMINDER_LINK_MAX_AGE
    seconds.  No authentication required — the signed token is the credential.
    """
    from apps.payments.services.reminder import REMINDER_LINK_MAX_AGE

    try:
        order_ref = signing.loads(
            token, salt="payment-reminder", max_age=REMINDER_LINK_MAX_AGE
        )
    except signing.SignatureExpired:
        return render(request, "payments/link_expired.html", status=410)
    except signing.BadSignature:
        return render(request, "payments/link_expired.html", status=410)

    order = get_object_or_404(Order, reference=order_ref)

    if order.status == Order.STATUS_PAID:
        return render(request, "payments/already_paid.html", {"order": order})

    # Only pending orders can be resumed.  Cancelled, refunded, and expired
    # orders must not create new Stripe sessions.
    if order.status != Order.STATUS_PENDING:
        return render(request, "payments/link_expired.html", status=410)

    # Create a fresh Stripe Checkout session using SITE_URL so the
    # success/cancel URLs are correct even though there is no live request
    # origin to derive them from.
    origin = settings.SITE_URL.rstrip("/")
    session = create_checkout_session(request, order, origin=origin)
    return redirect(session.redirect_url, permanent=False)
