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
