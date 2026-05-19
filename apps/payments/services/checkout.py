"""
Checkout orchestration service.

Coordinates between the cart, booking service, Order model, and Stripe.
This is the brains — views just call these functions.

Flow:
  1. create_order_from_cart()   → Order + OrderItems + pending Bookings
  2. create_checkout_session()  → Stripe redirect URL
  3. confirm_order()            → mark paid, confirm bookings
  4. expire_pending_orders()    → cleanup stale pending orders
"""
import datetime
import logging
import time
from typing import Optional

from django.conf import settings
from django.db import transaction

from apps.booking.models import Booking
from apps.booking.services.booking import create_booking, confirm_booking
from apps.payments.interfaces import PaymentEvent
from apps.payments.models import Order, OrderItem, PaymentRecord, Voucher
from apps.payments.services.cart import (
    get_cart,
    cart_total_pence,
    get_voucher_discount,
    clear_cart,
    has_products,
    product_total_pence,
    ITEM_TYPE_BOOKING,
    ITEM_TYPE_PRODUCT,
)
from apps.payments.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


def _get_provider():
    return StripeService()


def _get_shipping(request) -> int:
    """Calculate shipping for the current cart."""
    if not has_products(request):
        return 0
    from apps.shop.models import ShopSettings
    shop = ShopSettings.load()
    return shop.shipping_cost(product_total_pence(request))


# ---------------------------------------------------------------------------
# Step 1: Build an Order from the cart
# ---------------------------------------------------------------------------

@transaction.atomic
def create_order_from_cart(
    request,
    client_name: str,
    client_email: str,
    client_phone: str = "",
) -> Order:
    """
    Snapshot the cart into an Order with OrderItems.
    Creates pending Bookings for booking items.
    Skips booking creation for product items.
    Clears the cart afterwards.

    Raises ValueError if the cart is empty.
    """
    cart = get_cart(request)
    if not cart:
        raise ValueError("Your cart is empty.")

    subtotal = cart_total_pence(request)
    shipping = _get_shipping(request)
    voucher_code, discount = get_voucher_discount(request)
    total = max(0, subtotal + shipping - discount)

    order = Order.objects.create(
        client_name=client_name.strip(),
        client_email=client_email.strip().lower(),
        client_phone=client_phone.strip(),
        subtotal_pence=subtotal,
        discount_pence=discount,
        total_pence=total,
        voucher_code=voucher_code or "",
    )

    for item in cart:
        item_type = item.get("item_type", ITEM_TYPE_BOOKING)

        if item_type == ITEM_TYPE_BOOKING:
            _create_booking_order_item(order, item, client_name, client_email, client_phone)
        elif item_type == ITEM_TYPE_PRODUCT:
            _create_product_order_item(order, item)

    # Redeem voucher if one was applied
    if voucher_code:
        try:
            voucher = Voucher.objects.get(code=voucher_code)
            voucher.redeem()
        except Voucher.DoesNotExist:
            pass

    clear_cart(request)
    return order


def _create_booking_order_item(order, item, client_name, client_email, client_phone):
    """Create an OrderItem + pending Booking for a booking cart item."""
    date = datetime.date.fromisoformat(item["date"])
    start_time = datetime.time.fromisoformat(item["start_time"])
    end_time = datetime.time.fromisoformat(item["end_time"])

    booking = create_booking(
        session_type_id=item["session_type_id"],
        location_id=item["location_id"],
        date=date,
        start_time=start_time,
        client_name=client_name.strip(),
        client_email=client_email.strip().lower(),
        client_phone=client_phone.strip(),
    )

    OrderItem.objects.create(
        order=order,
        item_type=ITEM_TYPE_BOOKING,
        booking=booking,
        session_type_id=item["session_type_id"],
        location_id=item["location_id"],
        date=date,
        start_time=start_time,
        end_time=end_time,
        price_pence=item["price_pence"],
        label=item["label"],
        quantity=1,
    )


def _create_product_order_item(order, item):
    """Create an OrderItem for a product cart item."""
    OrderItem.objects.create(
        order=order,
        item_type=ITEM_TYPE_PRODUCT,
        product_id=item["product_id"],
        price_pence=item["price_pence"],
        quantity=item.get("qty", 1),
        label=item["label"],
    )


# ---------------------------------------------------------------------------
# Step 2: Create Stripe session
# ---------------------------------------------------------------------------

def create_checkout_session(request, order: Order):
    """
    Create a Stripe Checkout session for an Order.
    Returns the PaymentSession with the redirect URL.
    """
    scheme = "https" if request.is_secure() else "http"
    origin = f"{scheme}://{request.get_host()}"
    success_url = origin + "/payments/success/?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = origin + "/payments/cancel/"

    # Stripe minimum expiry is 30 minutes
    stripe_expires_at = int(time.time()) + 1800

    item_count = order.items.count()
    booking_count = order.items.filter(item_type=ITEM_TYPE_BOOKING).count()
    product_count = order.items.filter(item_type=ITEM_TYPE_PRODUCT).count()

    if item_count == 1:
        product_name = order.items.first().label
    elif booking_count and product_count:
        product_name = f"ReachSwim — {booking_count} session(s) + {product_count} item(s)"
    elif booking_count:
        product_name = f"ReachSwim — {booking_count} session(s)"
    else:
        product_name = f"ReachSwim — {product_count} item(s)"

    return _get_provider().create_payment_session(
        amount_pence=order.total_pence,
        currency="gbp",
        product_name=product_name,
        order_reference=str(order.reference),
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=order.client_email,
        expires_at=stripe_expires_at,
    )


# ---------------------------------------------------------------------------
# Step 3: Confirm payment (called from webhook or success-page fallback)
# ---------------------------------------------------------------------------

@transaction.atomic
def confirm_order(event: PaymentEvent) -> Optional[Order]:
    """
    Idempotent confirmation.  Marks Order as paid, confirms all Bookings,
    creates PaymentRecord.

    Returns the Order or None if the order_reference is unknown.
    """
    # Idempotency: already processed this event?
    if PaymentRecord.objects.filter(stripe_event_id=event.provider_event_id).exists():
        logger.info("Duplicate event %s — skipping.", event.provider_event_id)
        return None

    try:
        order = Order.objects.select_for_update().get(
            reference=event.order_reference,
        )
    except Order.DoesNotExist:
        logger.warning("Order %s not found for event %s",
                        event.order_reference, event.provider_event_id)
        return None

    # Already paid?
    if order.status == Order.STATUS_PAID:
        return order

    # Mark paid
    order.status = Order.STATUS_PAID
    order.stripe_payment_intent_id = event.payment_intent_id
    order.save(update_fields=["status", "stripe_payment_intent_id", "updated_at"])

    # Confirm each booking (skip product items — nothing to confirm)
    for oi in order.items.select_related("booking"):
        if oi.is_booking and oi.booking and oi.booking.status == Booking.STATUS_PENDING:
            confirm_booking(oi.booking, payment_intent_id=event.payment_intent_id)

    # Deduct stock for product items
    for oi in order.items.select_related("product"):
        if oi.is_product and oi.product:
            product = oi.product
            if product.stock >= oi.quantity:
                product.stock -= oi.quantity
                product.save(update_fields=["stock"])

    # Audit log
    PaymentRecord.objects.create(
        order=order,
        order_reference=str(order.reference),
        event_type="checkout.session.completed",
        stripe_event_id=event.provider_event_id,
        amount_pence=event.amount_pence,
        currency=event.currency,
        raw_payload=event.raw_payload,
    )

    return order


# ---------------------------------------------------------------------------
# Success-page fallback (like Jetski)
# ---------------------------------------------------------------------------

def confirm_from_session_id(session_id: str) -> Optional[Order]:
    """
    Called from the success page when the webhook hasn't fired yet.
    Verifies with Stripe directly and confirms the order.
    """
    if not session_id or session_id.startswith("{"):
        return None

    try:
        import stripe as _stripe
        _stripe.api_key = settings.STRIPE_SECRET_KEY
        session = _stripe.checkout.Session.retrieve(session_id)

        if session.payment_status != "paid":
            return None

        order_ref = (session.metadata or {}).get("order_reference")
        if not order_ref:
            return None

        event = PaymentEvent(
            order_reference=order_ref,
            amount_pence=session.amount_total,
            currency=(session.currency or "gbp").upper(),
            provider_event_id=f"success_{session.id}",
            payment_intent_id=session.payment_intent or "",
            raw_payload={"session_id": session_id},
        )
        return confirm_order(event)

    except Exception:
        logger.exception("confirm_from_session_id failed for %s", session_id)
        return None
