"""
Generate unique, unguessable voucher codes for package session credits.

One responsibility: produce a code string that does not already exist in
the Voucher table.  UUID4-based so brute-force is not feasible.
"""
import uuid


def generate_unique_code() -> str:
    """
    Return a URL-safe, uppercase code derived from a UUID4.

    Format: XXXXXXXX-XXXX-XXXX  (first 18 hex chars in two groups).
    Collision probability is negligible but we still check uniqueness before
    returning so callers never have to handle a duplicate.
    """
    from apps.payments.models import Voucher

    while True:
        raw = uuid.uuid4().hex.upper()
        code = f"{raw[:8]}-{raw[8:12]}-{raw[12:18]}"
        if not Voucher.objects.filter(code=code).exists():
            return code
