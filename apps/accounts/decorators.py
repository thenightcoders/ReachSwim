"""
Access control decorators for the dashboard.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def owner_required(view_func):
    """
    Decorator that checks:
      1. User is authenticated → redirect to login if not
      2. User has owner or staff role (can_access_dashboard) → 403 if wrong role
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            login_url = getattr(settings, "LOGIN_URL", "/account/login/")
            return redirect(f"{login_url}?next={request.path}")
        if not request.user.can_access_dashboard:
            raise PermissionDenied("You don't have permission to access the dashboard.")
        return view_func(request, *args, **kwargs)
    return _wrapped
