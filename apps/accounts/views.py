"""
Account views — login, logout, register, profile.

Thin HTTP layer. Forms do the validation, views just wire things up.
"""
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import LoginForm, RegisterForm, ProfileForm


def login_view(request):
    """Email + password login."""
    if request.user.is_authenticated:
        return _post_login_redirect(request.user)

    if request.method == "POST":
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Respect ?next= param, otherwise redirect by role
            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url:
                return redirect(next_url)
            return _post_login_redirect(user)
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


def logout_view(request):
    """Log out and redirect to homepage."""
    logout(request)
    return redirect("pages:home")


def register_view(request):
    """Client registration."""
    if request.user.is_authenticated:
        return _post_login_redirect(request.user)

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("accounts:profile")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile_view(request):
    """View/edit profile. Also shows booking history for clients."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    # Fetch this user's bookings (matched by email)
    from apps.booking.models import Booking
    bookings = Booking.objects.filter(
        client_email__iexact=request.user.email,
    ).select_related("session_type", "location").order_by("-date", "-start_time")

    return render(request, "accounts/profile.html", {
        "form": form,
        "bookings": bookings,
    })


def _post_login_redirect(user):
    """Redirect owner/staff to dashboard, clients to profile."""
    if user.can_access_dashboard:
        return redirect("dashboard:home")
    return redirect("accounts:profile")
