"""
Account views — login, logout, register, profile.

Auth methods (priority order):
  1. Magic link — email a single-use signed token
  2. Passkey — WebAuthn discoverable credentials (Face ID, YubiKey, etc.)
  3. Password — classic email + password fallback

Thin HTTP layer. Forms do the validation, views just wire things up.
"""
import base64
import json

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import LoginForm, RegisterForm, ProfileForm, ChangePasswordForm, ChangeEmailForm


def login_view(request):
    """
    Combined login page — three sections:
      1. Magic link (primary)
      2. Passkey (secondary)
      3. Password form (fallback, collapsed)
    """
    if request.user.is_authenticated:
        return _post_login_redirect(request.user)

    # Password form only handles POST when the password section is submitted
    if request.method == "POST" and request.POST.get("auth_method") == "password":
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.get_user()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
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
    """View/edit profile. Also shows booking history and draft bookings for clients."""
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
    from apps.booking.services.availability import get_slot, next_available_slot

    bookings = (
        Booking.objects
        .filter(Q(user=request.user) | Q(client_email__iexact=request.user.email))
        .exclude(status=Booking.STATUS_DRAFT)
        .select_related("session_type", "location")
        .order_by("-date", "-start_time")
        .distinct()
    )

    active_bookings_count = bookings.filter(
        status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED]
    ).count()

    # Draft bookings: saved when a cart reservation expired before checkout.
    # Enriched with live availability so the template can show "slot gone" warnings.
    draft_bookings_qs = (
        Booking.objects
        .filter(
            Q(user=request.user) | Q(client_email__iexact=request.user.email),
            status=Booking.STATUS_DRAFT,
        )
        .select_related("session_type", "location")
        .order_by("-created_at")
        .distinct()
    )

    draft_bookings = []
    for draft in draft_bookings_qs:
        slot = get_slot(draft.session_type_id, draft.location_id, draft.date, draft.start_time)
        slot_available = slot is not None and slot.is_available
        suggestion = None
        if not slot_available:
            suggestion = next_available_slot(
                draft.session_type_id, draft.location_id, from_date=draft.date,
            )
        draft_bookings.append({
            "booking": draft,
            "slot_available": slot_available,
            "suggestion": suggestion,
        })

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
        "draft_bookings": draft_bookings,
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
    """Redirect after login based on role.
    ADMIN_EMAIL lands on the homepage — no forced destination, goes wherever they want.
    Owner/staff → dashboard. Client → profile.
    """
    from django.conf import settings
    if user.email == getattr(settings, "ADMIN_EMAIL", ""):
        return redirect("pages:home")
    if user.can_access_dashboard:
        return redirect("dashboard:home")
    return redirect("accounts:profile")


# ---------------------------------------------------------------------------
# Magic Link
# ---------------------------------------------------------------------------

def magic_link_send_view(request):
    """
    POST — accept an email, send a magic link if the account exists.
    Always renders the "check your email" page regardless — no enumeration.
    """
    if request.method != "POST":
        return redirect("accounts:login")

    email = request.POST.get("email", "").strip().lower()

    if email:
        from .models import User
        from .services.magic_link import send_magic_link
        try:
            user = User.objects.get(email=email, is_active=True)
            send_magic_link(user, request)
        except User.DoesNotExist:
            pass  # silent — don't leak whether the email exists
        except Exception:
            pass  # don't expose email backend errors to the browser

    return render(request, "accounts/magic_link_sent.html", {"email": email})


def magic_link_verify_view(request):
    """GET — verify token param, log the user in."""
    from .services.magic_link import verify_magic_link

    token_str = request.GET.get("token", "")
    user, error = verify_magic_link(token_str)

    if error:
        messages.error(request, error)
        return redirect("accounts:login")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, f"Welcome back, {user.first_name or user.email}!")
    next_url = request.GET.get("next", "")
    if next_url:
        return redirect(next_url)
    return _post_login_redirect(user)


# ---------------------------------------------------------------------------
# Passkey (WebAuthn)
# ---------------------------------------------------------------------------

def passkey_auth_challenge_view(request):
    """
    POST — generate a WebAuthn authentication challenge.
    No credentials list — discoverable flow, no username needed.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    from .services.passkey import generate_authentication_options
    import webauthn

    options = generate_authentication_options()
    # Stash raw challenge bytes in session (base64 so it survives JSON serialisation)
    request.session["passkey_auth_challenge"] = base64.b64encode(options.challenge).decode()

    return JsonResponse(json.loads(webauthn.options_to_json(options)))


def passkey_auth_complete_view(request):
    """
    POST — verify the authenticator assertion, look up the credential, log in.
    Body: JSON credential from navigator.credentials.get()
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    challenge_b64 = request.session.pop("passkey_auth_challenge", None)
    if not challenge_b64:
        return JsonResponse({"error": "No active challenge. Start over."}, status=400)

    challenge_bytes = base64.b64decode(challenge_b64)

    try:
        body = request.body.decode()
        cred_data = json.loads(body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Look up which credential this is — credential_id arrives as base64url
    raw_id_b64 = cred_data.get("rawId") or cred_data.get("id", "")
    # Add padding before decoding
    padding = 4 - len(raw_id_b64) % 4
    if padding != 4:
        raw_id_b64 += "=" * padding
    credential_id_bytes = base64.urlsafe_b64decode(raw_id_b64)

    from .models import WebAuthnCredential
    try:
        stored = WebAuthnCredential.objects.select_related("user").get(
            credential_id=credential_id_bytes
        )
    except WebAuthnCredential.DoesNotExist:
        return JsonResponse({"error": "Unknown credential"}, status=400)

    from .services.passkey import verify_authentication
    try:
        verification = verify_authentication(
            body,
            challenge_bytes,
            stored.public_key,
            stored.sign_count,
        )
    except Exception as exc:
        return JsonResponse({"error": f"Authentication failed: {exc}"}, status=400)

    stored.sign_count = verification.new_sign_count
    stored.last_used_at = timezone.now()
    stored.save(update_fields=["sign_count", "last_used_at"])

    user = stored.user
    if not user.is_active:
        return JsonResponse({"error": "Account is disabled"}, status=403)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    from django.urls import reverse
    next_url = request.GET.get("next", "")
    if not next_url:
        from django.conf import settings
        if user.email == getattr(settings, "ADMIN_EMAIL", ""):
            next_url = reverse("pages:home")
        elif user.can_access_dashboard:
            next_url = reverse("dashboard:home")
        else:
            next_url = reverse("accounts:profile")

    return JsonResponse({"success": True, "redirect": next_url})


@login_required
def passkey_register_challenge_view(request):
    """
    POST — generate a WebAuthn registration challenge for the logged-in user.
    Used from the profile page to add a new passkey.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    from .services.passkey import generate_registration_options
    import webauthn

    options = generate_registration_options(request.user)
    request.session["passkey_register_challenge"] = base64.b64encode(options.challenge).decode()

    return JsonResponse(json.loads(webauthn.options_to_json(options)))


@login_required
def passkey_register_complete_view(request):
    """
    POST — verify the attestation and store the new credential.
    Body: JSON credential from navigator.credentials.create(), plus optional `name` field.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    challenge_b64 = request.session.pop("passkey_register_challenge", None)
    if not challenge_b64:
        return JsonResponse({"error": "No active challenge. Refresh and try again."}, status=400)

    challenge_bytes = base64.b64decode(challenge_b64)

    try:
        body = request.body.decode()
        payload = json.loads(body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Extract optional user-supplied name before passing to verify (it's not part of spec JSON)
    passkey_name = payload.pop("name", "Passkey") or "Passkey"

    from .services.passkey import verify_registration
    try:
        verification = verify_registration(json.dumps(payload), challenge_bytes)
    except Exception as exc:
        return JsonResponse({"error": f"Registration failed: {exc}"}, status=400)

    from .models import WebAuthnCredential
    WebAuthnCredential.objects.create(
        user=request.user,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        aaguid=str(verification.aaguid) if verification.aaguid else "",
        name=passkey_name[:100],
    )

    return JsonResponse({"success": True})


@login_required
@require_POST
def passkey_delete_view(request, pk):
    """POST — remove a passkey credential owned by the logged-in user."""
    from .models import WebAuthnCredential
    try:
        cred = WebAuthnCredential.objects.get(pk=pk, user=request.user)
        cred.delete()
        messages.success(request, "Passkey removed.")
    except WebAuthnCredential.DoesNotExist:
        messages.error(request, "Passkey not found.")
    return redirect("accounts:profile")


# ---------------------------------------------------------------------------
# Draft bookings
# ---------------------------------------------------------------------------

@login_required
@require_POST
def resume_draft_view(request, booking_id):
    """
    Re-activate a draft booking: create a fresh pending reservation (with the
    same race-condition guard as a normal add-to-cart), cancel the draft, and
    drop the new pending booking into the cart.

    If the slot is gone, bounce back to the profile page — the template already
    shows the next-available suggestion for each draft.
    """
    import time as _time
    from apps.booking.models import Booking, SessionPricing
    from apps.booking.services.booking import create_booking, cancel_booking
    from apps.booking.services.availability import get_slot
    from apps.booking.services.booking import SlotUnavailableError
    from apps.payments.services import cart as cart_svc

    try:
        draft = Booking.objects.select_related("session_type", "location").get(
            pk=booking_id,
            status=Booking.STATUS_DRAFT,
        )
    except Booking.DoesNotExist:
        messages.error(request, "Draft not found.")
        return redirect("accounts:profile")

    # Ownership check
    if not (
        draft.user_id == request.user.pk
        or draft.client_email.lower() == request.user.email.lower()
    ):
        messages.error(request, "You don't have permission to resume this draft.")
        return redirect("accounts:profile")

    # Verify the slot is still open before touching the DB
    slot = get_slot(draft.session_type_id, draft.location_id, draft.date, draft.start_time)
    if not slot or not slot.is_available:
        messages.error(
            request,
            f"The original slot for ‘{draft.session_type.name}’ is no longer available. "
            "We’ve highlighted an alternative below.",
        )
        return redirect("accounts:profile#drafts")

    # Create a fresh pending booking (select_for_update inside create_booking
    # serialises concurrent attempts and raises SlotUnavailableError if needed).
    try:
        new_booking = create_booking(
            session_type_id=draft.session_type_id,
            location_id=draft.location_id,
            date=draft.date,
            start_time=draft.start_time,
            client_name=getattr(request.user, "full_name", None) or request.user.email,
            client_email=request.user.email,
            user=request.user,
        )
    except SlotUnavailableError as exc:
        messages.error(request, str(exc))
        return redirect("accounts:profile")

    # Draft's slot is now held by the new pending booking — safe to purge.
    cancel_booking(draft, notify_client=False)

    # Price: SessionPricing is canonical; fall back to what was recorded at
    # booking time if the pricing row was deleted.
    try:
        pricing = SessionPricing.objects.get(
            session_type_id=draft.session_type_id,
            location_id=draft.location_id,
        )
        price_pence = pricing.price_pence
    except SessionPricing.DoesNotExist:
        price_pence = draft.amount_pence

    label = (
        f"{draft.session_type.name} @ {draft.location.name} — "
        f"{draft.date.strftime('%a %-d %b')} {draft.start_time.strftime('%H:%M')}"
    )
    cart_svc.add_to_cart(
        request,
        session_type_id=draft.session_type_id,
        location_id=draft.location_id,
        date_str=draft.date.isoformat(),
        start_time=draft.start_time.strftime("%H:%M"),
        end_time=draft.end_time.strftime("%H:%M"),
        price_pence=price_pence,
        label=label,
        booking_id=new_booking.id,
        reserved_at=_time.time(),
    )
    cart_svc.auto_apply_credit_for_booking(
        request,
        session_type_id=draft.session_type_id,
        location_id=draft.location_id,
        price_pence=price_pence,
    )

    messages.success(
        request,
        f"‘{draft.session_type.name}’ re-added to your cart. "
        "You have 5 minutes to complete checkout.",
    )
    return redirect("accounts:profile")


@login_required
@require_POST
def dismiss_draft_view(request, booking_id):
    """POST — permanently dismiss (cancel) a draft booking."""
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking

    try:
        draft = Booking.objects.get(pk=booking_id, status=Booking.STATUS_DRAFT)
    except Booking.DoesNotExist:
        messages.error(request, "Draft not found.")
        return redirect("accounts:profile")

    if not (
        draft.user_id == request.user.pk
        or draft.client_email.lower() == request.user.email.lower()
    ):
        messages.error(request, "Permission denied.")
        return redirect("accounts:profile")

    cancel_booking(draft, notify_client=False)
    messages.success(request, "Draft removed.")
    return redirect("accounts:profile")
