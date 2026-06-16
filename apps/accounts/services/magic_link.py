"""
Magic link service — generate, email, and verify single-use login tokens.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from apps.accounts.models import MagicLinkToken


def send_magic_link(user, request):
    """
    Create a fresh token for the user and fire the login email.
    Any previously pending tokens are wiped before issuing the new one.
    """
    token = MagicLinkToken.create_for_user(user)
    verify_url = request.build_absolute_uri(
        reverse("accounts:magic_link_verify") + f"?token={token.token}"
    )

    send_mail(
        subject="Your ReachSwim login link",
        message=(
            f"Hi {user.first_name or user.email},\n\n"
            f"Click the link below to log in to ReachSwim. "
            f"It expires in {MagicLinkToken.EXPIRY_MINUTES} minutes and can only be used once.\n\n"
            f"{verify_url}\n\n"
            f"If you didn't request this, just ignore it — your account is safe."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def verify_magic_link(token_str):
    """
    Validate a token string.
    Returns (user, None) on success, (None, error_message) on failure.
    """
    if not token_str:
        return None, "Invalid login link."

    try:
        token = MagicLinkToken.objects.select_related("user").get(
            token=token_str,
            used=False,
        )
    except MagicLinkToken.DoesNotExist:
        return None, "This link is invalid or has already been used."

    if token.is_expired:
        token.delete()
        return None, "This link has expired. Request a new one."

    if not token.user.is_active:
        return None, "This account is disabled."

    token.used = True
    token.save(update_fields=["used"])
    return token.user, None
