"""
Tests for apps/accounts — views, managers, email validation.
"""
import importlib
import sys
import types
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

# ---------------------------------------------------------------------------
# Stub out py3-validate-email so tests run even when the package isn't installed.
# If it IS installed, sys.modules already has the real thing — we skip injection.
# ---------------------------------------------------------------------------
if importlib.util.find_spec("validate_email") is None:
    _stub_ve = types.ModuleType("validate_email")
    _stub_exc = types.ModuleType("validate_email.exceptions")

    class _Base(Exception):
        pass

    class AddressFormatError(_Base):
        pass

    class DomainBlacklistedError(_Base):
        pass

    class EmailValidationError(_Base):
        pass

    class DNSError(EmailValidationError):
        pass

    class DomainNotFoundError(DNSError):
        pass

    class NoMXError(DNSError):
        pass

    class SMTPError(EmailValidationError):
        pass

    class AddressNotDeliverableError(SMTPError):
        pass

    class SMTPTemporaryError(SMTPError):
        pass

    for _cls in (
        AddressFormatError, DomainBlacklistedError, EmailValidationError,
        DNSError, DomainNotFoundError, NoMXError,
        SMTPError, AddressNotDeliverableError, SMTPTemporaryError,
    ):
        setattr(_stub_exc, _cls.__name__, _cls)

    _stub_ve.validate_email_or_fail = MagicMock(return_value=None)
    _stub_ve.validate_email = MagicMock(return_value=True)
    _stub_ve.exceptions = _stub_exc

    sys.modules["validate_email"] = _stub_ve
    sys.modules["validate_email.exceptions"] = _stub_exc

from apps.accounts.email_validator import EmailCheckResult, validate_email_address  # noqa: E402

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


# ---------------------------------------------------------------------------
# Email whitespace — UserManager
# ---------------------------------------------------------------------------

class UserManagerNormalizationTest(TestCase):
    """
    Manager._create_user must strip whitespace before storing the email.
    Bug: ' user@example.com ' would pass the unique constraint (different
    string) but then fail login because the login form strips its input.
    """

    def test_leading_trailing_spaces_are_stripped(self):
        user = User.objects.create_user(
            email="  stripped@example.com  ",
            password="pass",
            full_name="Space Test",
        )
        self.assertEqual(user.email, "stripped@example.com")

    def test_tabs_and_newlines_are_stripped(self):
        user = User.objects.create_user(
            email="\tleading@example.com\n",
            password="pass",
            full_name="Tab Test",
        )
        self.assertEqual(user.email, "leading@example.com")

    def test_user_created_with_spaces_can_log_in(self):
        """
        Historical bug: register with padded email → login fails.
        After the fix, stored email is clean so the login lookup succeeds.
        """
        User.objects.create_user(
            email="  login@example.com  ",
            password="supersecure1",
            full_name="Login Test",
        )
        logged_in = self.client.login(
            username="login@example.com", password="supersecure1",
        )
        self.assertTrue(logged_in, "User created with padded email could not log in")

    def test_duplicate_detection_works_after_stripping(self):
        """Creating the same email with and without spaces must hit the unique constraint."""
        User.objects.create_user(
            email="dupe@example.com", password="pass", full_name="First",
        )
        with self.assertRaises(Exception):  # IntegrityError / ValidationError
            User.objects.create_user(
                email="  dupe@example.com  ", password="pass", full_name="Second",
            )

    def test_normalize_email_lowercases_domain(self):
        """Django's normalize_email lowercases the domain part — confirm it's still applied."""
        user = User.objects.create_user(
            email="User@EXAMPLE.COM", password="pass", full_name="Case Test",
        )
        self.assertEqual(user.email, "User@example.com")


# ---------------------------------------------------------------------------
# email_validator module
# ---------------------------------------------------------------------------

class EmailValidatorModuleTest(TestCase):
    """
    Unit tests for apps.accounts.email_validator.validate_email_address().

    Mocks validate_email_or_fail at the module level so these run whether
    or not py3-validate-email is installed.
    """

    def _ve_or_fail(self):
        """Return the name to patch — always the one bound in our module."""
        return "apps.accounts.email_validator.validate_email_or_fail"

    def _exc(self, name: str):
        """Retrieve an exception class from whichever validate_email.exceptions is loaded."""
        return getattr(sys.modules["validate_email.exceptions"], name)

    # --- happy path ---

    def test_valid_email_returns_true(self):
        with patch(self._ve_or_fail(), return_value=None):
            result = validate_email_address("good@example.com")
        self.assertTrue(result.valid)
        self.assertIsNone(result.reason)

    def test_result_is_truthy_when_valid(self):
        with patch(self._ve_or_fail(), return_value=None):
            result = validate_email_address("good@example.com")
        self.assertTrue(bool(result))

    # --- format errors ---

    def test_bad_format_returns_friendly_message(self):
        with patch(self._ve_or_fail(), side_effect=self._exc("AddressFormatError")()):
            result = validate_email_address("notanemail")
        self.assertFalse(result.valid)
        self.assertIn("valid email", result.reason)

    def test_result_is_falsy_when_invalid(self):
        with patch(self._ve_or_fail(), side_effect=self._exc("AddressFormatError")()):
            result = validate_email_address("notanemail")
        self.assertFalse(bool(result))

    # --- blacklist ---

    def test_disposable_domain_returns_friendly_message(self):
        with patch(self._ve_or_fail(), side_effect=self._exc("DomainBlacklistedError")()):
            result = validate_email_address("user@mailnull.com")
        self.assertFalse(result.valid)
        self.assertIn("Disposable", result.reason)

    # --- DNS errors ---

    def test_domain_not_found_maps_to_friendly_message(self):
        with patch(self._ve_or_fail(), side_effect=self._exc("DomainNotFoundError")()):
            result = validate_email_address("user@totallyfake123456.xyz", check_dns=True)
        self.assertFalse(result.valid)
        self.assertIn("doesn't exist", result.reason)

    def test_no_mx_maps_to_friendly_message(self):
        with patch(self._ve_or_fail(), side_effect=self._exc("NoMXError")()):
            result = validate_email_address("user@nomx.example", check_dns=True)
        self.assertFalse(result.valid)
        self.assertIn("MX", result.reason)

    # --- checks tracking ---

    def test_default_checks_are_format_and_blacklist(self):
        with patch(self._ve_or_fail(), return_value=None):
            result = validate_email_address("good@example.com")
        self.assertEqual(result.checks, ["format", "blacklist"])

    def test_dns_check_appears_in_checks_list_when_enabled(self):
        with patch(self._ve_or_fail(), return_value=None):
            result = validate_email_address("good@example.com", check_dns=True)
        self.assertIn("dns", result.checks)


# ---------------------------------------------------------------------------
# Email validation wired into RegisterForm
# ---------------------------------------------------------------------------

class RegisterFormValidationTest(TestCase):
    """
    The registration form must reject disposable addresses and bad formats
    via validate_email_address, and must always strip whitespace from input.
    """

    BASE_DATA = {
        "full_name": "New Swimmer",
        "phone": "",
        "password": "strongpass1",
        "password_confirm": "strongpass1",
    }

    def _post(self, email, **extra):
        return self.client.post(
            reverse("accounts:register"),
            {**self.BASE_DATA, "email": email, **extra},
        )

    # --- whitespace ---

    def test_form_strips_whitespace_from_email(self):
        """Django's EmailField strips before clean_email is called."""
        with patch(
            "apps.accounts.forms.validate_email_address",
            return_value=EmailCheckResult(valid=True),
        ):
            self._post("  padded@example.com  ")
        # If no error, the user should be stored with the clean address
        self.assertTrue(User.objects.filter(email="padded@example.com").exists())

    # --- disposable domain ---

    def test_disposable_email_is_rejected_by_form(self):
        with patch(
            "apps.accounts.forms.validate_email_address",
            return_value=EmailCheckResult(
                valid=False,
                reason="Disposable or temporary email addresses are not accepted.",
            ),
        ) as mock_val:
            response = self._post("user@mailnull.com")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="user@mailnull.com").exists())
        mock_val.assert_called_once_with("user@mailnull.com")

    # --- bad format ---

    def test_bad_format_email_is_rejected_by_form(self):
        with patch(
            "apps.accounts.forms.validate_email_address",
            return_value=EmailCheckResult(
                valid=False,
                reason="Enter a valid email address.",
            ),
        ):
            response = self._post("notanemail@")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="notanemail@").exists())

    # --- error message surfaced in response ---

    def test_validation_error_reason_appears_in_response(self):
        with patch(
            "apps.accounts.forms.validate_email_address",
            return_value=EmailCheckResult(
                valid=False,
                reason="Disposable or temporary email addresses are not accepted.",
            ),
        ):
            response = self._post("user@throwam.com")

        self.assertContains(
            response,
            "Disposable or temporary email addresses are not accepted.",
        )
