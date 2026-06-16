"""
Account views — login, logout, register, profile.

Thin HTTP layer. Forms do the validation, views just wire things up.
"""
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import LoginForm, RegisterForm, ProfileForm, ChangePasswordForm, ChangeEmailForm


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

    from django.db.models import Q
    from apps.booking.models import Booking
    from apps.payments.models import PackagePurchase

    bookings = (
        Booking.objects
        .filter(Q(user=request.user) | Q(client_email__iexact=request.user.email))
        .select_related("session_type", "location")
        .order_by("-date", "-start_time")
        .distinct()
    )

    active_bookings_count = bookings.exclude(status=Booking.STATUS_CANCELLED).count()  # noqa

    package_purchases = (
        PackagePurchase.objects
        .filter(Q(user=request.user) | Q(client_email__iexact=request.user.email))
        .select_related("package__session_type", "package__location")
        .order_by("-purchased_at")
        .distinct()
    )

    return render(request, "accounts/profile.html", {
        "form": form,
        "bookings": bookings,
        "package_purchases": package_purchases,
        "active_bookings_count": active_bookings_count,
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


@login_required
def change_password_view(request):
    """Change password flow — requires current password."""
    if request.method == "POST":
        form = ChangePasswordForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password"])
            request.user.save()
            # Keep the session alive after password change
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password updated.")
            return redirect("accounts:profile")
    else:
        form = ChangePasswordForm(user=request.user)

    return render(request, "accounts/change_password.html", {"form": form})


@login_required
def change_email_view(request):
    """Change email flow — requires current password confirmation."""
    if request.method == "POST":
        form = ChangeEmailForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.email = form.cleaned_data["new_email"]
            request.user.save(update_fields=["email"])
            messages.success(request, "Email address updated.")
            return redirect("accounts:profile")
    else:
        form = ChangeEmailForm(user=request.user)

    return render(request, "accounts/change_email.html", {"form": form})


def _post_login_redirect(user):
    """Redirect owner/staff to dashboard, clients to profile."""
    if user.can_access_dashboard:
        return redirect("dashboard:home")
    return redirect("accounts:profile")
