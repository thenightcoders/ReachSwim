"""
Tests for apps/accounts/views.py

Fix 6 — LogoutSecurityTest:
  logout_view must be POST-only.  A GET request (e.g. an <img> tag on a
  third-party page) must NOT log the user out.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

LOGOUT_URL = reverse("accounts:logout")


class LogoutSecurityTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="correcthorse",
            full_name="Test User",
        )

    def _login(self):
        self.client.login(username="test@example.com", password="correcthorse")

    # ------------------------------------------------------------------
    # POST — should work
    # ------------------------------------------------------------------

    def test_post_logout_logs_user_out(self):
        self._login()
        self.assertTrue(self.client.session.get("_auth_user_id"))

        response = self.client.post(LOGOUT_URL)

        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_post_logout_redirects_to_homepage(self):
        self._login()
        response = self.client.post(LOGOUT_URL)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_logout_works_when_already_anonymous(self):
        """Logging out when not logged in should not error."""
        response = self.client.post(LOGOUT_URL)
        self.assertIn(response.status_code, (200, 302))

    # ------------------------------------------------------------------
    # GET — must be rejected (CSRF protection)
    # ------------------------------------------------------------------

    def test_get_logout_returns_405(self):
        """GET /account/logout/ must return 405, not log the user out."""
        self._login()
        response = self.client.get(LOGOUT_URL)

        self.assertEqual(response.status_code, 405)

    def test_get_logout_does_not_log_user_out(self):
        """A GET request must leave the session intact."""
        self._login()
        self.client.get(LOGOUT_URL)

        self.assertTrue(self.client.session.get("_auth_user_id"),
                        "User should still be authenticated after GET logout attempt")


# ---------------------------------------------------------------------------
# Login view
# ---------------------------------------------------------------------------

class LoginViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="swim@example.com",
            password="correcthorse",
            full_name="Swimmer One",
            role="client",
        )

    def test_get_renders_login_page(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<form")

    def test_valid_credentials_log_in_and_redirect(self):
        response = self.client.post(reverse("accounts:login"), {
            "email": "swim@example.com",
            "password": "correcthorse",
        })
        # Client role → profile page
        self.assertRedirects(
            response, reverse("accounts:profile"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_wrong_password_stays_on_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "email": "swim@example.com",
            "password": "wronghorse",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_unknown_email_stays_on_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "email": "nobody@example.com",
            "password": "irrelevant",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(reverse("accounts:login"), {
            "email": "swim@example.com",
            "password": "correcthorse",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_owner_redirected_to_dashboard(self):
        owner = User.objects.create_user(
            email="owner@reachswim.co.uk",
            password="ownerpass",
            full_name="Coach Maren",
            role="owner",
        )
        response = self.client.post(reverse("accounts:login"), {
            "email": "owner@reachswim.co.uk",
            "password": "ownerpass",
        })
        self.assertRedirects(
            response, reverse("dashboard:home"),
            fetch_redirect_response=False,
        )

    def test_already_logged_in_redirects_without_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:login"))
        # Should redirect away from login for authenticated users
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# Register view
# ---------------------------------------------------------------------------

class RegisterViewTest(TestCase):

    VALID_DATA = {
        "email": "new@example.com",
        "full_name": "New Swimmer",
        "phone": "07700 900000",
        "password": "strongpass1",
        "password_confirm": "strongpass1",
    }

    def test_get_renders_register_page(self):
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 200)

    def test_valid_registration_creates_client_user(self):
        self.client.post(reverse("accounts:register"), self.VALID_DATA)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, User.ROLE_CLIENT)
        self.assertEqual(user.full_name, "New Swimmer")

    def test_valid_registration_logs_in(self):
        self.client.post(reverse("accounts:register"), self.VALID_DATA)
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_valid_registration_redirects_to_profile(self):
        response = self.client.post(reverse("accounts:register"), self.VALID_DATA)
        self.assertRedirects(
            response, reverse("accounts:profile"),
            fetch_redirect_response=False,
        )

    def test_mismatched_passwords_rejected(self):
        data = {**self.VALID_DATA, "password_confirm": "differentpass"}
        response = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            email="new@example.com", full_name="Existing", password="pass"
        )
        response = self.client.post(reverse("accounts:register"), self.VALID_DATA)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email="new@example.com").count(), 1)

    def test_already_logged_in_redirects(self):
        user = User.objects.create_user(
            email="existing@example.com", full_name="Existing", password="pass"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# Profile view
# ---------------------------------------------------------------------------

class ProfileViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="profile@example.com",
            password="pass",
            full_name="Profile User",
            phone="",
            role="client",
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login/", response["Location"])

    def test_authenticated_renders_profile(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)

    def test_profile_update_saves_name_and_phone(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:profile"), {
            "full_name": "Updated Name",
            "phone": "07700 123456",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Updated Name")
        self.assertEqual(self.user.phone, "07700 123456")

    def test_profile_update_redirects_to_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:profile"), {
            "full_name": "Updated",
            "phone": "",
        })
        self.assertRedirects(
            response, reverse("accounts:profile"),
            fetch_redirect_response=False,
        )

    def test_bookings_listed_in_context(self):
        """Profile view must pass user's bookings matched by email."""
        from apps.booking.models import Booking, SessionType, Location
        import datetime

        st = SessionType.objects.create(
            name="Private", slug="priv-profile", duration_minutes=60, is_active=True
        )
        loc = Location.objects.create(
            name="Pool D", slug="pool-d", address="4 Test Ln", is_active=True
        )
        Booking.objects.create(
            session_type=st, location=loc,
            date=datetime.date(2030, 6, 1),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            client_name="Profile User",
            client_email="profile@example.com",
            status=Booking.STATUS_CONFIRMED,
            amount_pence=7000,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertIn("bookings", response.context)
        self.assertEqual(response.context["bookings"].count(), 1)
