"""
Package purchase creation.

One responsibility: given a package and buyer details, create the
PackagePurchase record and generate one Voucher credit per session.
"""
import datetime

from django.utils import timezone

from apps.booking.models import Package
from apps.payments.models import PackagePurchase, Voucher
from apps.payments.services.code_generator import generate_unique_code


def create_purchase(
    package: Package,
    client_name: str,
    client_email: str,
    stripe_payment_intent_id: str = "",
    user=None,
) -> PackagePurchase:
    """Create a PackagePurchase and its associated Voucher credits."""
    client_email = client_email.strip().lower()

    expires_at = timezone.now() + datetime.timedelta(days=package.valid_days)

    purchase = PackagePurchase.objects.create(
        package=package,
        user=user,
        client_name=client_name,
        client_email=client_email,
        amount_pence=package.price_pence,
        stripe_payment_intent_id=stripe_payment_intent_id,
        expires_at=expires_at,
    )

    _generate_vouchers(purchase, package, expires_at, client_email)
    return purchase


def _generate_vouchers(
    purchase: PackagePurchase,
    package: Package,
    expires_at: datetime.datetime,
    client_email: str,
) -> list[Voucher]:
    """Create one single-use full-credit Voucher per session in the package."""
    vouchers = [
        Voucher(
            code=generate_unique_code(),
            discount_type=Voucher.DISCOUNT_FULL,
            allowed_email=client_email,
            session_type=package.session_type,
            location=package.location,
            package_purchase=purchase,
            max_uses=1,
            valid_from=timezone.now(),
            valid_until=expires_at,
        )
        for _ in range(package.session_count)
    ]
    Voucher.objects.bulk_create(vouchers)
    return vouchers


def migrate_to_account(user) -> int:
    """
    Link orphan PackagePurchases (no user, matching email) to a newly
    registered account.  Called from the accounts post_save signal.

    Returns the number of purchases migrated.
    """
    email = user.email.strip().lower()
    updated = (
        PackagePurchase.objects
        .filter(client_email=email, user__isnull=True)
        .update(user=user)
    )
    return updated
