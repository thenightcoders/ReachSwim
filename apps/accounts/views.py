"""
Account views — login, logout, register, profile.

Thin HTTP layer. Forms do the validation, views just wire things up.
"""
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

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
    """Log out and redirect to homepage. POST logs out; GET redirects harmlessly."""
    if request.method == "POST":
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
            messages.success(request, "Welcome to ReachSwim! Your account is ready.")
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
            messages.success(request, "Changes saved.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    # Fetch this user's bookings.
    # Prefer the direct FK (set on bookings made while logged in) and also
    # catch any guest bookings that share the same email — deduped via distinct().
    from django.db.models import Q
    from apps.booking.models import Booking
    bookings = (
        Booking.objects
        .filter(Q(user=request.user) | Q(client_email__iexact=request.user.email))
        .select_related("session_type", "location")
        .order_by("-date", "-start_time")
        .distinct()
    )

    return render(request, "accounts/profile.html", {
        "form": form,
        "bookings": bookings,
    })


@login_required
@require_POST
def cancel_booking_view(request, reference):
    """
    Cancel a booking owned by the logged-in user.

    Ownership is verified by matching client_email to request.user.email.
    Only pending/confirmed bookings that haven't started yet can be cancelled.
    """
    from django.contrib import messages
    from apps.booking.models import Booking
    from apps.booking.services.booking import (
        cancel_booking_for_client,
        CancellationWindowError,
    )

    try:
        booking = Booking.objects.get(reference=reference)
    except Booking.DoesNotExist:
        messages.error(request, "Booking not found.")
        return redirect("accounts:profile")

    try:
        cancel_booking_for_client(booking, client_email=request.user.email)
    except PermissionError as exc:
        messages.error(request, str(exc))
    except ValueError as exc:
        messages.error(request, str(exc))
    except CancellationWindowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your booking has been cancelled.")
    return redirect("accounts:profile")


def _post_login_redirect(user):
    """Redirect owner/staff to dashboard, clients to profile."""
    if user.can_access_dashboard:
        return redirect("dashboard:home")
    return redirect("accounts:profile")
