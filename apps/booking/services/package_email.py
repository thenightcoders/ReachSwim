"""
Package purchase confirmation email.

One responsibility: send the post-purchase email containing the session
credit codes and clear instructions on when (not) to use them.
"""
from django.core.mail import send_mail
from django.conf import settings

from apps.payments.models import PackagePurchase, Voucher


def send_purchase_confirmation(
    purchase: PackagePurchase,
    vouchers: list[Voucher],
) -> None:
    """
    Email the buyer their session credit codes.

    Logged-in users are reminded they do not need the codes to book —
    their credits are already on their account.  The codes exist as a
    fallback for booking while logged out.
    """
    subject = f"Your {purchase.package.name} package — session credits inside"
    body = _build_body(purchase, vouchers)

    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[purchase.client_email],
        fail_silently=False,
    )


def _build_body(purchase: PackagePurchase, vouchers: list[Voucher]) -> str:
    codes = "\n".join(f"  {i + 1}. {v.code}" for i, v in enumerate(vouchers))
    expires = purchase.expires_at.strftime("%d %B %Y")
    pool = purchase.package.location.name
    session = purchase.package.session_type.name

    return f"""Hi {purchase.client_name},

Your {purchase.package.name} package is confirmed.

You have {len(vouchers)} session credit(s) for:
  Session type : {session}
  Pool         : {pool}
  Valid until  : {expires}

Your session codes:
{codes}

--- HOW TO USE ---

If you have an account with us (or create one with this email address),
you do NOT need these codes. Your credits are already linked to your
account and will be applied automatically at checkout — just log in and book.

Only use a code above if you are booking WITHOUT logging in. At checkout,
enter the code in the voucher field to use one credit. You will receive
your booking confirmation and calendar invite by email.

Questions? Reply to this email.

ReachSwim
"""
