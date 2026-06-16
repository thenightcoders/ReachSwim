from django.conf import settings
from django.shortcuts import redirect


class AdminEmailGuardMiddleware:
    """
    Guards /admin/ — only the ADMIN_EMAIL user gets through.
    Everyone else is redirected somewhere sensible:
      - not logged in  → homepage
      - owner / staff  → dashboard
      - client         → profile
    Must sit after AuthenticationMiddleware so request.user is populated.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            admin_email = getattr(settings, "ADMIN_EMAIL", "")
            if admin_email and request.user.is_authenticated and request.user.email == admin_email:
                return self.get_response(request)

            # Not the admin — redirect somewhere sensible
            if not request.user.is_authenticated:
                return redirect("pages:home")
            if request.user.can_access_dashboard:
                return redirect("dashboard:home")
            return redirect("accounts:profile")

        return self.get_response(request)
