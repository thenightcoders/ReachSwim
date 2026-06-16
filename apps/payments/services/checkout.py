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

from django.db import transaction
from django.db.models import F

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
    ITEM_TYPE_PACKAGE,
)
from apps.payments.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


def _get_provider():
    return StripeService()


def _get_shipping(request) -> int:
    """
    Calculate shipping for the current cart.

    Per-product overrides take precedence over the global ShopSettings rate.
    If any product in the cart has shipping_override_pence set, the highest
    override value is used (covers the most expensive item to ship).
    Falls back to ShopSettings.shipping_rate_pence when no overrides exist.
    Free-shipping threshold is always checked first.
    """
    if not has_products(request):
        return 0

    from apps.shop.models import ShopSettings, Product

    shop = ShopSettings.load()
    product_total = product_total_pence(request)

    if product_total >= shop.free_shipping_threshold_pence:
        return 0

    cart = get_cart(request)
    product_ids = [
        item["product_id"]
        for item in cart
        if item.get("item_type") == ITEM_TYPE_PRODUCT
    ]

    overrides = list(
        Product.objects.filter(
            pk__in=product_ids,
            shipping_override_pence__isnull=False,
        ).values_list("shipping_override_pence", flat=True)
    )

    return max(overrides) if overrides else shop.shipping_rate_pence


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
            _create_booking_order_item(
                order, item, client_name, client_email, client_phone,
                user=request.user,
            )
        elif item_type == ITEM_TYPE_PRODUCT:
            _create_product_order_item(order, item)
        elif item_type == ITEM_TYPE_PACKAGE:
            _create_package_order_item(order, item)

    # Redeem voucher if one was applied.
    # select_for_update() acquires a row lock and is_valid() re-checks
    # dates + usage cap inside this transaction — prevents two concurrent
    # checkouts from both redeeming the same single-use code.
    if voucher_code:
        try:
            voucher = Voucher.objects.select_for_update().get(code=voucher_code)
            # Re-check email here for the guest flow: at cart-apply time the
            # email was unknown so the validator skipped it. Now we have the
            # real client_email and enforce the restriction before redeeming.
            email_ok = (
                not voucher.allowed_email
                or voucher.allowed_email == order.client_email
            )
            if email_ok and voucher.is_valid(subtotal):
                voucher.redeem()
        except Voucher.DoesNotExist:
            pass

    clear_cart(request)
    return order


def _create_booking_order_item(order, item, client_name, client_email, client_phone, user=None):
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
        user=user,
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


def _create_package_order_item(order, item):
    """Create an OrderItem for a package cart item."""
    OrderItem.objects.create(
        order=order,
        item_type=ITEM_TYPE_PACKAGE,
        package_id=item["package_id"],
        price_pence=item["price_pence"],
        quantity=1,
        label=item["label"],
    )


# ---------------------------------------------------------------------------
# Step 2: Create Stripe session
# ---------------------------------------------------------------------------

def create_checkout_session(request, order: Order, *, origin: str = ""):
    """
    Create a Stripe Checkout session for an Order.
    Returns the PaymentSession with the redirect URL.

    Pass ``origin`` explicitly (e.g. settings.SITE_URL) when generating a
    session outside a live HTTP request — the payment-reminder resume view
    does this so the success/cancel URLs resolve correctly.
    Falls back to deriving the origin from ``request`` when omitted.
    """
    if not origin:
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

    # Fulfil package items — create PackagePurchase + Voucher credits + email.
    _fulfil_package_items(order, event)

    # Deduct stock for product items atomically.
    # F() expression pushes the arithmetic to the DB in a single UPDATE,
    # preventing the read-modify-write race condition.
    # The stock__gte guard ensures we never go below zero.
    for oi in order.items.filter(item_type=ITEM_TYPE_PRODUCT):
        if oi.product_id:
            from apps.shop.models import Product
            Product.objects.filter(
                pk=oi.product_id,
                stock__gte=oi.quantity,
            ).update(stock=F("stock") - oi.quantity)

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
# Success-page fallback
# ---------------------------------------------------------------------------

def confirm_from_session_id(session_id: str) -> Optional[Order]:
    """
    Called from the success page when the webhook hasn't fired yet.
    Delegates to the payment provider to retrieve and verify the session —
    no direct Stripe SDK imports here, so swapping providers needs no change.
    """
    try:
        event = _get_provider().retrieve_completed_session(session_id)
    except Exception:
        logger.exception("confirm_from_session_id failed for %s", session_id)
        return None

    if event is None:
        return None
    return confirm_order(event)


# ---------------------------------------------------------------------------
# Step 4: Cancel a pending order (user abandoned checkout / clicked cancel)
# ---------------------------------------------------------------------------

@transaction.atomic
def cancel_pending_order(order_reference: str) -> None:
    """
    Cancel all pending Bookings tied to a pending Order, then mark the
    Order itself as expired.

    Called from the cancel page (user aborted Stripe checkout) and from
    expire_pending_orders() (stale cleanup).  Safe to call multiple times —
    idempotent because we filter on STATUS_PENDING.
    """
    from apps.booking.services.booking import cancel_booking as _cancel_booking

    try:
        order = Order.objects.select_for_update().get(
            reference=order_reference,
            status=Order.STATUS_PENDING,
        )
    except Order.DoesNotExist:
        return  # already paid or expired — nothing to do

    # Cancel every pending booking attached to this order
    for oi in order.items.select_related("booking"):
        if oi.is_booking and oi.booking and oi.booking.status == "pending":
            _cancel_booking(oi.booking, reason="Payment cancelled by customer.")

    order.status = Order.STATUS_EXPIRED
    order.save(update_fields=["status", "updated_at"])


def _fulfil_package_items(order: Order, event: "PaymentEvent") -> None:
    """Create PackagePurchase + vouchers + send email for each package item."""
    from apps.booking.services.package_purchase import create_purchase
    from apps.booking.services.package_email import send_purchase_confirmation

    package_items = order.items.filter(
        item_type=ITEM_TYPE_PACKAGE
    ).select_related("package__session_type", "package__location")

    for oi in package_items:
        from apps.accounts.models import User
        user = None
        try:
            user = User.objects.get(email=order.client_email)
        except User.DoesNotExist:
            pass

        purchase = create_purchase(
            package=oi.package,
            client_name=order.client_name,
            client_email=order.client_email,
            stripe_payment_intent_id=event.payment_intent_id,
            user=user,
        )
        vouchers = list(purchase.vouchers.all())
        try:
            send_purchase_confirmation(purchase, vouchers)
        except Exception:
            logger.exception(
                "Failed to send package confirmation email for purchase %s",
                purchase.reference,
            )


def expire_pending_orders(older_than_minutes: int = 35) -> int:
    """
    Bulk-cancel all pending orders (and their bookings) that are older than
    ``older_than_minutes``.  Returns the number of orders expired.

    Stripe sessions expire after 30 min; we use 35 min to give the webhook a
    little slack before we clean up.  Call this from a management command or
    a scheduled task.
    """
    from django.utils import timezone

    cutoff = timezone.now() - datetime.timedelta(minutes=older_than_minutes)
    stale = Order.objects.filter(
        status=Order.STATUS_PENDING,
        created_at__lt=cutoff,
    ).values_list("reference", flat=True)

    count = 0
    for ref in stale:
        cancel_pending_order(str(ref))
        count += 1

    if count:
        logger.info("expire_pending_orders: expired %d stale orders.", count)
    return count
