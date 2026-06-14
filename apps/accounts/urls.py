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
]
