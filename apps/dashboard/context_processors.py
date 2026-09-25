"""
Dashboard context processor — injects sidebar badges into every dashboard response.
"""


def dashboard_context(request):
    """
    Injects unread_message_count, quarantine_count and spam_api_down (drives
    the "spam check is down" banner) into every template rendered while the user
    is authenticated and has dashboard access.  Skipped for anonymous users to
    avoid a needless DB hit on public pages.
    """
    if not request.user.is_authenticated or not getattr(request.user, "can_access_dashboard", False):
        return {}

    from apps.legal.models import ContactMessage, SpamCheckStatus

    quarantine_count = ContactMessage.objects.quarantine().count()
    return {
        "unread_message_count": ContactMessage.objects.inbox().filter(is_read=False).count(),
        "quarantine_count": quarantine_count,
        "spam_api_down": bool(quarantine_count) and SpamCheckStatus.load().api_ok is False,
    }
