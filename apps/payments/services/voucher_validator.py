"""
Voucher validation — one function, one responsibility.

Rules enforced in order:
1. Normalise code + email (lowercase, stripped).
2. Fetch with select_for_update to block concurrent redemptions.
3. Code not found OR email mismatch  →  same generic error (no enumeration).
   Email check is skipped when email is empty (guest at cart-apply stage).
   Full email verification is deferred to checkout for the guest flow.
4. Location mismatch  →  specific helpful error (code is real, just wrong pool).
5. Session-type mismatch  →  generic error (don't leak what the code is for).
6. is_valid() checks active / dates / max_uses / min_order.
"""
from django.db import transaction

from apps.payments.models import Voucher


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _normalise_code(code: str) -> str:
    return code.strip().upper()


_GENERIC_ERROR = "Invalid or expired code."


@transaction.atomic
def validate(
    code: str,
    email: str,
    session_type_id: int | None,
    location_id: int | None,
    subtotal_pence: int,
) -> Voucher:
    """
    Validate a voucher code and return the Voucher instance.

    Acquires a row-level lock (select_for_update) so two simultaneous requests
    for the same single-use code cannot both pass validation before either
    increments times_used.

    Raises ValueError with a user-facing message on any failure.
    """
    code = _normalise_code(code)
    email = _normalise_email(email)

    try:
        voucher = (
            Voucher.objects
            .select_for_update()
            .get(code=code)
        )
    except Voucher.DoesNotExist:
        raise ValueError(_GENERIC_ERROR)

    # Email restriction — same error as "not found" to prevent enumeration.
    # Skip when email is empty: guest users don't have an email at cart-apply
    # time. The checkout service re-validates with the real client_email before
    # redeeming, so skipping here does not bypass the restriction end-to-end.
    if email and voucher.allowed_email and _normalise_email(voucher.allowed_email) != email:
        raise ValueError(_GENERIC_ERROR)

    # Location mismatch — helpful, because switching pools fixes the problem.
    if voucher.location_id and voucher.location_id != location_id:
        raise ValueError(
            f"This voucher is only valid at {voucher.location.name}."
        )

    # Session-type mismatch — generic, don't reveal what the code is for.
    if voucher.session_type_id and voucher.session_type_id != session_type_id:
        raise ValueError(_GENERIC_ERROR)

    if not voucher.is_valid(subtotal_pence):
        raise ValueError(_GENERIC_ERROR)

    return voucher
