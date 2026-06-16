"""
Session-based shopping cart.

Cart data lives in Django's session (server-side by default).
No models, no database — just dicts in the session store.

Two item types:
  - "booking"  → swim session slot (unique by session_type + location + date + time)
  - "product"  → physical product   (unique by product_id; quantity stacks)
"""
from typing import List, Optional, Tuple

CART_SESSION_KEY = "reachswim_cart"
VOUCHER_SESSION_KEY = "reachswim_voucher"

ITEM_TYPE_BOOKING = "booking"
ITEM_TYPE_PRODUCT = "product"
ITEM_TYPE_PACKAGE = "package"


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
) -> List[dict]:
    """
    Add a booking item to the cart.  Silently ignores duplicates.
    Returns the updated cart.
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
    """Empty the cart and remove any applied voucher."""
    request.session.pop(CART_SESSION_KEY, None)
    clear_voucher(request)


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
# Voucher in session
# ---------------------------------------------------------------------------

def apply_voucher(request, code: str) -> int:
    """
    Validate and store a voucher code in the session.
    Returns the discount in pence.
    Raises ValueError with a user-facing message on failure.
    """
    from apps.payments.services.voucher_validator import validate

    # Derive context from cart for session-type / location checks.
    cart = get_cart(request)
    booking = next((i for i in cart if i.get("item_type") == ITEM_TYPE_BOOKING), None)
    session_type_id = booking["session_type_id"] if booking else None
    location_id = booking["location_id"] if booking else None

    # Email: use authenticated user's address if logged in, otherwise unknown
    # at this point — full email check happens at checkout.
    email = ""
    if hasattr(request, "user") and request.user.is_authenticated:
        email = request.user.email

    subtotal = cart_total_pence(request)
    voucher = validate(code, email, session_type_id, location_id, subtotal)

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
