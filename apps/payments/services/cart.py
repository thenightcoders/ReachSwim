"""
Session-based shopping cart.

Cart data lives in Django's session (server-side by default).
No models, no database — just dicts in the session store.

Two item types:
  - "booking"  → swim session slot (unique by session_type + location + date + time)
  - "product"  → physical product   (unique by product_id; quantity stacks)
"""
import time
from typing import List, Optional, Tuple

CART_SESSION_KEY = "reachswim_cart"
VOUCHER_SESSION_KEY = "reachswim_voucher"
CREDITS_SESSION_KEY = "reachswim_credits"  # list of {code, discount_pence}

ITEM_TYPE_BOOKING = "booking"
ITEM_TYPE_PRODUCT = "product"
ITEM_TYPE_PACKAGE = "package"

# Cart-level reservations expire after this many seconds.
# Keeps a slot from being blocked indefinitely by someone who never pays.
# Distinct from the Order-level 35-min window (expire_pending_orders) which
# kicks in once a user has clicked through to Stripe.
CART_RESERVATION_TTL = 5 * 60  # 5 minutes


def _cart_key(item: dict) -> tuple:
    """
    Uniqueness key.
    Bookings: (booking, session_type_id, location_id, date, start_time)
    Products: (product, product_id)
    Packages: (package, package_id)  — one package per cart
    """
    if item.get("item_type") == ITEM_TYPE_PRODUCT:
        return (ITEM_TYPE_PRODUCT, item["product_id"])
    if item.get("item_type") == ITEM_TYPE_PACKAGE:
        return (ITEM_TYPE_PACKAGE, item["package_id"])
    return (
        ITEM_TYPE_BOOKING,
        item["session_type_id"],
        item["location_id"],
        item["date"],
        item["start_time"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cart(request) -> List[dict]:
    """Return the current cart contents."""
    return request.session.get(CART_SESSION_KEY, [])


def add_to_cart(
    request,
    session_type_id: int,
    location_id: int,
    date_str: str,
    start_time: str,
    end_time: str,
    price_pence: int,
    label: str,
    booking_id: Optional[int] = None,
    reserved_at: Optional[float] = None,
) -> List[dict]:
    """
    Add a booking item to the cart.  Silently ignores duplicates.
    Returns the updated cart.

    booking_id:  pk of a pending Booking reserved at cart-add time.
    reserved_at: time.time() when the slot was reserved — used for TTL expiry.
    """
    cart = get_cart(request)
    new_item = {
        "item_type": ITEM_TYPE_BOOKING,
        "session_type_id": session_type_id,
        "location_id": location_id,
        "date": date_str,
        "start_time": start_time,
        "end_time": end_time,
        "price_pence": price_pence,
        "label": label,
        "qty": 1,
        "booking_id": booking_id,
        "reserved_at": reserved_at,
    }

    # Prevent duplicates
    new_key = _cart_key(new_item)
    for item in cart:
        if _cart_key(item) == new_key:
            return cart

    cart.append(new_item)
    request.session[CART_SESSION_KEY] = cart
    return cart


def add_product_to_cart(
    request,
    product_id: int,
    name: str,
    color: str,
    price_pence: int,
    qty: int = 1,
    photo_class: str = "",
    image_url: str = "",
) -> List[dict]:
    """
    Add a product to the cart.  Stacks quantity on duplicates.
    Returns the updated cart.
    """
    cart = get_cart(request)
    new_key = (ITEM_TYPE_PRODUCT, product_id)

    for item in cart:
        if _cart_key(item) == new_key:
            item["qty"] += qty
            request.session[CART_SESSION_KEY] = cart
            return cart

    cart.append({
        "item_type": ITEM_TYPE_PRODUCT,
        "product_id": product_id,
        "name": name,
        "color": color,
        "price_pence": price_pence,
        "qty": qty,
        "photo_class": photo_class,
        "image_url": image_url,
        "label": f"{name} — {color}" if color else name,
    })
    request.session[CART_SESSION_KEY] = cart
    return cart


def update_product_qty(request, product_id: int, qty: int) -> List[dict]:
    """
    Set product quantity.  If qty <= 0, removes the item.
    Returns the updated cart.
    """
    cart = get_cart(request)
    target_key = (ITEM_TYPE_PRODUCT, product_id)

    new_cart = []
    for item in cart:
        if _cart_key(item) == target_key:
            if qty > 0:
                item["qty"] = qty
                new_cart.append(item)
            # else: skip (remove)
        else:
            new_cart.append(item)

    request.session[CART_SESSION_KEY] = new_cart
    return new_cart


def remove_from_cart(request, index: int) -> List[dict]:
    """Remove item by index.  Returns updated cart."""
    cart = get_cart(request)
    if 0 <= index < len(cart):
        cart.pop(index)
        request.session[CART_SESSION_KEY] = cart
    return cart


def clear_cart(request):
    """Empty the cart and remove any applied voucher and credits."""
    request.session.pop(CART_SESSION_KEY, None)
    clear_voucher(request)
    clear_credits(request)


def cart_count(request) -> int:
    return sum(item.get("qty", 1) for item in get_cart(request))


def cart_total_pence(request) -> int:
    return sum(
        item["price_pence"] * item.get("qty", 1) for item in get_cart(request)
    )


def add_package_to_cart(
    request,
    package_id: int,
    name: str,
    price_pence: int,
    label: str,
) -> List[dict]:
    """
    Add a package to the cart.  Silently ignores duplicates.
    Returns the updated cart.
    """
    cart = get_cart(request)
    new_item = {
        "item_type": ITEM_TYPE_PACKAGE,
        "package_id": package_id,
        "price_pence": price_pence,
        "label": label,
        "name": name,
        "qty": 1,
    }
    new_key = _cart_key(new_item)
    if any(_cart_key(i) == new_key for i in cart):
        return cart
    cart.append(new_item)
    request.session[CART_SESSION_KEY] = cart
    return cart


def has_products(request) -> bool:
    """Return True if the cart contains at least one product item."""
    return any(
        item.get("item_type") == ITEM_TYPE_PRODUCT for item in get_cart(request)
    )


def product_total_pence(request) -> int:
    """Return subtotal of just the product items."""
    return sum(
        item["price_pence"] * item.get("qty", 1)
        for item in get_cart(request)
        if item.get("item_type") == ITEM_TYPE_PRODUCT
    )


# ---------------------------------------------------------------------------
# Cart reservation TTL
# ---------------------------------------------------------------------------

def _cancel_booking_by_id(booking_id: int) -> None:
    """
    Cancel a pending Booking by pk.
    Used when the user explicitly removes a booking from the cart.
    No-op if already cancelled/confirmed/draft.
    """
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking
    try:
        bk = Booking.objects.get(pk=booking_id, status=Booking.STATUS_PENDING)
        cancel_booking(bk, notify_client=False)
    except Booking.DoesNotExist:
        pass


def _downgrade_to_draft_by_id(booking_id: int, user) -> None:
    """
    Downgrade a pending Booking to STATUS_DRAFT when the cart TTL expires.

    Authenticated users: the draft is saved to their profile so they can resume it.
    Guests (no user): no account to surface the draft, so cancel outright instead.
    """
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking, downgrade_to_draft
    try:
        bk = Booking.objects.get(pk=booking_id, status=Booking.STATUS_PENDING)
        if user and getattr(user, "is_authenticated", False):
            downgrade_to_draft(bk)
        else:
            cancel_booking(bk, notify_client=False)
    except Booking.DoesNotExist:
        pass


def check_and_expire_reservations(request) -> List[str]:
    """
    Scan the cart for booking items whose 5-minute reservation window has
    passed.  For authenticated users, the underlying pending Booking is
    downgraded to STATUS_DRAFT (saved to their profile for later resumption).
    For guests, it is cancelled outright.  Either way the cart item is removed.

    Returns a list of labels for expired items so the view can tell the user.

    Note: count_for_slot already auto-excludes stale pending bookings from
    availability counts — this function is the complementary clean-up that
    keeps the user's own cart drawer in sync.
    """
    cart = get_cart(request)
    now = time.time()
    expired_labels: List[str] = []
    surviving = []
    user = getattr(request, "user", None)

    for item in cart:
        if item.get("item_type") != ITEM_TYPE_BOOKING:
            surviving.append(item)
            continue
        reserved_at = item.get("reserved_at")
        booking_id = item.get("booking_id")
        if reserved_at and (now - reserved_at) > CART_RESERVATION_TTL:
            if booking_id:
                _downgrade_to_draft_by_id(booking_id, user)
            expired_labels.append(item.get("label", "Session"))
        else:
            surviving.append(item)

    if expired_labels:
        request.session[CART_SESSION_KEY] = surviving
        request.session.modified = True

    return expired_labels


# ---------------------------------------------------------------------------
# Voucher in session
# ---------------------------------------------------------------------------

def auto_apply_credit_for_booking(
    request,
    session_type_id: int,
    location_id: int,
    price_pence: int,
) -> bool:
    """
    Called from cart_add immediately after a booking is successfully added.
    Finds one unused package credit matching this booking's session type and
    location, and appends it to the credits list in the session.

    Only applies if:
    - user is authenticated
    - a matching unused credit exists
    - that credit's code isn't already in the session (idempotent)

    Returns True if a credit was applied.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return False

    from apps.payments.models import Voucher
    from django.utils import timezone

    # Codes already applied — don't double-apply the same voucher.
    manual_code = get_voucher_discount(request)[0]
    used_codes: set = {c["code"] for c in get_credits(request)}
    if manual_code:
        used_codes.add(manual_code)

    now = timezone.now()
    voucher = (
        Voucher.objects
        .filter(
            package_purchase__user=request.user,
            session_type_id=session_type_id,
            location_id=location_id,
            times_used=0,
            is_active=True,
            valid_from__lte=now,
            valid_until__gte=now,
        )
        .exclude(code__in=used_codes)
        .first()
    )
    if not voucher:
        return False

    credits = get_credits(request)
    credits.append({"code": voucher.code, "discount_pence": price_pence})
    request.session[CREDITS_SESSION_KEY] = credits
    request.session.modified = True
    return True

# ---------------------------------------------------------------------------
# Package credits (auto-applied, one per booking)
# ---------------------------------------------------------------------------

def get_credits(request) -> List[dict]:
    """Return list of auto-applied credits: [{code, discount_pence}, ...]"""
    return list(request.session.get(CREDITS_SESSION_KEY, []))


def get_credits_total(request) -> int:
    """Total discount pence from all auto-applied credits."""
    return sum(c["discount_pence"] for c in get_credits(request))


def remove_credit(request, code: str) -> List[dict]:
    """Remove one specific credit by code. Returns the updated credits list."""
    credits = [c for c in get_credits(request) if c["code"] != code]
    request.session[CREDITS_SESSION_KEY] = credits
    request.session.modified = True
    return credits


def clear_credits(request) -> None:
    request.session.pop(CREDITS_SESSION_KEY, None)


def apply_voucher(request, code: str) -> int:
    """
    Validate and store a voucher code in the session.
    Returns the discount in pence.
    Raises ValueError with a user-facing message on failure.

    Multi-booking carts: tries each unique (session_type, location) pair in
    the cart until validation passes.  This means a voucher for session type B
    at pool Y won't be rejected just because session type A at pool X happens
    to be first in the cart.

    Full-type vouchers (package credits): discounts only ONE matching booking's
    price, not the entire cart subtotal.  A single credit redeems one session.
    """
    from apps.payments.models import Voucher as VoucherModel
    from apps.payments.services.voucher_validator import validate

    cart = get_cart(request)
    bookings = [i for i in cart if i.get("item_type") == ITEM_TYPE_BOOKING]

    # Email: use authenticated user's address if logged in, otherwise unknown
    # at this point — full email check happens at checkout.
    email = ""
    if hasattr(request, "user") and request.user.is_authenticated:
        email = request.user.email

    subtotal = cart_total_pence(request)

    # Try each unique (session_type, location) pair in the cart.
    # validate() is read-only (no writes), so calling it in a loop is safe.
    voucher = None
    matched_booking = None
    last_error: Optional[ValueError] = None

    if not bookings:
        # No bookings in cart — validate without type/location context.
        voucher = validate(code, email, None, None, subtotal)
    else:
        seen_pairs: set = set()
        for booking in bookings:
            pair = (booking["session_type_id"], booking["location_id"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            try:
                voucher = validate(
                    code, email,
                    booking["session_type_id"],
                    booking["location_id"],
                    subtotal,
                )
                matched_booking = booking
                break
            except ValueError as exc:
                last_error = exc

        if voucher is None:
            raise last_error or ValueError("Invalid or expired code.")

    # For full-type vouchers (package credits): the credit covers ONE session,
    # not the whole cart.  Use the matched booking's price as the discount so
    # a second booking in the same cart still charges full price.
    if voucher.discount_type == VoucherModel.DISCOUNT_FULL and matched_booking:
        discount = matched_booking["price_pence"]
    else:
        discount = voucher.calculate_discount(subtotal)

    request.session[VOUCHER_SESSION_KEY] = {
        "code": voucher.code,
        "discount_pence": discount,
    }
    return discount


def get_voucher_discount(request) -> Tuple[Optional[str], int]:
    """Return (code, discount_pence) or (None, 0)."""
    data = request.session.get(VOUCHER_SESSION_KEY)
    if data:
        return data["code"], data["discount_pence"]
    return None, 0


def clear_voucher(request):
    request.session.pop(VOUCHER_SESSION_KEY, None)
