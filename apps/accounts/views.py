"""
Account views — login, logout, register, profile.

Thin HTTP layer. Forms do the validation, views just wire things up.
"""
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


@require_POST
def logout_view(request):
    """Log out and redirect to homepage. POST-only to prevent CSRF logout."""
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


@login_required
@require_POST
def cancel_booking_view(request, reference):
    """
    Cancel a booking owned by the logged-in user.

    Ownership is verified by matching client_email to request.user.email.
    Only pending/confirmed bookings that haven't started yet can be cancelled.
    """
    import uuid as _uuid
    from django.contrib import messages
    from django.utils import timezone
    from apps.booking.models import Booking, BookingSettings
    from apps.booking.services.booking import cancel_booking

    try:
        booking = Booking.objects.get(reference=reference)
    except (Booking.DoesNotExist, ValueError):
        messages.error(request, "Booking not found.")
        return redirect("accounts:profile")

    # Ownership check — email must match the logged-in user
    if booking.client_email.lower() != request.user.email.lower():
        messages.error(request, "You don't have permission to cancel this booking.")
        return redirect("accounts:profile")

    # Only cancellable if still pending or confirmed
    if booking.status not in (Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED):
        messages.error(request, "This booking cannot be cancelled.")
        return redirect("accounts:profile")

    # Check cancellation window
    bs = BookingSettings.load()
    session_start = timezone.datetime.combine(booking.date, booking.start_time)
    session_start = timezone.make_aware(session_start)
    hours_until = (session_start - timezone.now()).total_seconds() / 3600

    if hours_until < bs.cancellation_hours:
        messages.error(
            request,
            f"Bookings can only be cancelled at least {bs.cancellation_hours} hours before the session.",
        )
        return redirect("accounts:profile")

    cancel_booking(booking, reason="Cancelled by client via profile.")
    messages.success(request, "Your booking has been cancelled.")
    return redirect("accounts:profile")


def _post_login_redirect(user):
    """Redirect owner/staff to dashboard, clients to profile."""
    if user.can_access_dashboard:
        return redirect("dashboard:home")
    return redirect("accounts:profile")
