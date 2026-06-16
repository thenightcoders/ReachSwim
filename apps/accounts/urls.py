from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/change-password/", views.change_password_view, name="change_password"),
    path("profile/change-email/", views.change_email_view, name="change_email"),
    path("bookings/<uuid:reference>/cancel/", views.cancel_booking_view, name="booking_cancel"),

    # Magic link
    path("magic-link/send/", views.magic_link_send_view, name="magic_link_send"),
    path("magic-link/verify/", views.magic_link_verify_view, name="magic_link_verify"),

    # Passkey (WebAuthn)
    path("passkey/auth/challenge/", views.passkey_auth_challenge_view, name="passkey_auth_challenge"),
    path("passkey/auth/complete/", views.passkey_auth_complete_view, name="passkey_auth_complete"),
    path("passkey/register/challenge/", views.passkey_register_challenge_view, name="passkey_register_challenge"),
    path("passkey/register/complete/", views.passkey_register_complete_view, name="passkey_register_complete"),
    path("passkey/<int:pk>/delete/", views.passkey_delete_view, name="passkey_delete"),
]
