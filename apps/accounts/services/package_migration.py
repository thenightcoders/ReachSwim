"""
Migrate orphan package purchases to a newly registered account.

One responsibility: when a user registers, find any PackagePurchase rows
whose client_email matches and link them (and their Voucher credits) to
the new User record so the account shows credits without requiring codes.
"""
from apps.booking.services.package_purchase import migrate_to_account


def on_user_registered(user) -> None:
    """
    Entry point called from the post_save signal after a new User is created.
    Delegates entirely to package_purchase.migrate_to_account.
    """
    migrate_to_account(user)
