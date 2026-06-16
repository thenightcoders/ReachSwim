"""
Account signals.

One responsibility: wire Django signals for the accounts app.
Currently: post_save on User → migrate orphan package purchases.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


def _get_user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()


@receiver(post_save)
def migrate_packages_on_registration(sender, instance, created, **kwargs):
    """Link orphan PackagePurchases to an account the moment it is created."""
    if not created:
        return
    if sender is not _get_user_model():
        return

    from apps.accounts.services.package_migration import on_user_registered
    on_user_registered(instance)
