"""
Dashboard context processor — injects sidebar badges into every dashboard response.
"""


def dashboard_context(request):
    """
    Injects unread_message_count into every template rendered while the user
    is authenticated and has dashboard access.  Skipped for anonymous users to
    avoid a needless DB hit on public pages.
    """
    if not request.user.is_authenticated or not getattr(request.user, "can_access_dashboard", False):
        return {}

    from apps.legal.models import ContactMessage

    return {
        "unread_message_count": ContactMessage.objects.filter(is_read=False).count(),
    }
