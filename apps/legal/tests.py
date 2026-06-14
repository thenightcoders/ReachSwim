"""
Tests for apps/legal/views.py and apps/legal/models.py

Covers:
  - Contact form: GET renders form, POST saves message + redirects
  - Contact form: invalid submission stays on page with errors
  - LegalPage: active page renders, inactive returns 404
  - ContactMessage: admin mark_as_read / mark_as_unread actions
"""
from django.test import TestCase
from django.urls import reverse

from .models import ContactConfig, ContactMessage, LegalPage


CONTACT_URL = reverse("legal:contact")


# ---------------------------------------------------------------------------
# ContactMessage submission
# ---------------------------------------------------------------------------

class ContactFormTest(TestCase):

    def setUp(self):
        ContactConfig.load()  # ensure singleton exists

    def test_get_renders_form(self):
        response = self.client.get(CONTACT_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<form")

    def test_valid_post_creates_message(self):
        self.client.post(CONTACT_URL, {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "subject": "Question",
            "message": "Hello there.",
        })
        self.assertEqual(ContactMessage.objects.count(), 1)
        msg = ContactMessage.objects.first()
        self.assertEqual(msg.name, "Ada Lovelace")
        self.assertEqual(msg.email, "ada@example.com")
        self.assertFalse(msg.is_read)

    def test_valid_post_redirects(self):
        response = self.client.post(CONTACT_URL, {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "subject": "Question",
            "message": "Hello there.",
        })
        self.assertRedirects(response, CONTACT_URL, fetch_redirect_response=False)

    def test_missing_name_stays_on_page(self):
        response = self.client.post(CONTACT_URL, {
            "name": "",
            "email": "ada@example.com",
            "message": "Hello.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_missing_email_stays_on_page(self):
        response = self.client.post(CONTACT_URL, {
            "name": "Ada",
            "email": "",
            "message": "Hello.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_invalid_email_stays_on_page(self):
        response = self.client.post(CONTACT_URL, {
            "name": "Ada",
            "email": "not-an-email",
            "message": "Hello.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_missing_message_stays_on_page(self):
        response = self.client.post(CONTACT_URL, {
            "name": "Ada",
            "email": "ada@example.com",
            "message": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_subject_is_optional(self):
        """Subject is blank=True — submitting without it must still save."""
        response = self.client.post(CONTACT_URL, {
            "name": "Ada",
            "email": "ada@example.com",
            "subject": "",
            "message": "No subject.",
        })
        self.assertRedirects(response, CONTACT_URL, fetch_redirect_response=False)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_new_message_is_unread_by_default(self):
        self.client.post(CONTACT_URL, {
            "name": "Bob",
            "email": "bob@example.com",
            "message": "Hi.",
        })
        msg = ContactMessage.objects.first()
        self.assertFalse(msg.is_read)


# ---------------------------------------------------------------------------
# LegalPage rendering
# ---------------------------------------------------------------------------

class LegalPageViewTest(TestCase):

    def test_active_page_renders(self):
        page = LegalPage.objects.create(
            title="Privacy Policy",
            slug="privacy-policy",
            content="<p>Your data is safe.</p>",
            is_active=True,
        )
        response = self.client.get(reverse("legal:page", kwargs={"slug": page.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy Policy")

    def test_inactive_page_returns_404(self):
        LegalPage.objects.create(
            title="Draft Page",
            slug="draft-page",
            content="Not published.",
            is_active=False,
        )
        response = self.client.get(reverse("legal:page", kwargs={"slug": "draft-page"}))
        self.assertEqual(response.status_code, 404)

    def test_unknown_slug_returns_404(self):
        response = self.client.get(reverse("legal:page", kwargs={"slug": "does-not-exist"}))
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# ContactMessage admin actions
# ---------------------------------------------------------------------------

class ContactMessageAdminActionsTest(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            email="admin@reachswim.co.uk",
            password="adminpass",
            full_name="Admin",
        )
        self.client.force_login(self.admin_user)

        self.msg1 = ContactMessage.objects.create(
            name="Alice", email="alice@example.com", message="Hi"
        )
        self.msg2 = ContactMessage.objects.create(
            name="Bob", email="bob@example.com", message="Hello", is_read=True
        )

    def _action(self, action, ids):
        return self.client.post(
            "/admin/legal/contactmessage/",
            {
                "action": action,
                "_selected_action": ids,
            },
        )

    def test_mark_as_read_action(self):
        self._action("mark_as_read", [self.msg1.pk])
        self.msg1.refresh_from_db()
        self.assertTrue(self.msg1.is_read)

    def test_mark_as_unread_action(self):
        self._action("mark_as_unread", [self.msg2.pk])
        self.msg2.refresh_from_db()
        self.assertFalse(self.msg2.is_read)
