"""
Tests for apps/legal/views.py and apps/legal/models.py

Covers:
  - Contact form: GET renders form, POST saves message + redirects
  - Contact form: invalid submission stays on page with errors
  - LegalPage: active page renders, inactive returns 404
  - ContactMessage: admin mark_as_read / mark_as_unread actions
"""
import time
from unittest import mock

from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ContactConfig, ContactMessage, LegalPage
from .services import spam


CONTACT_URL = reverse("legal:contact")


def _rendered(seconds_ago=10):
    """A form timestamp as if the page was shown ``seconds_ago``."""
    return signing.dumps(time.time() - seconds_ago, salt=spam.TIMESTAMP_SALT)


# ---------------------------------------------------------------------------
# ContactMessage submission
# ---------------------------------------------------------------------------

@override_settings(SPAM_DETECTION_URL="")
class ContactFormTest(TestCase):

    def setUp(self):
        ContactConfig.load()  # ensure singleton exists
        # Every post in this class looks like a human who took 10s to type.
        post = self.client.post
        self.client.post = lambda url, data, **kw: post(url, {"rendered_at": _rendered(), **data}, **kw)

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
# Spam screening
# ---------------------------------------------------------------------------

GOOD = {"name": "Ada", "email": "ada@example.com", "subject": "Lessons", "message": "Do you teach beginners?"}


@override_settings(SPAM_DETECTION_URL="")
class ContactSpamTest(TestCase):

    def setUp(self):
        ContactConfig.load()

    def _post(self, **overrides):
        data = {**GOOD, "rendered_at": _rendered(), **overrides}
        return self.client.post(CONTACT_URL, data, REMOTE_ADDR="203.0.113.7")

    def test_human_message_goes_to_inbox(self):
        self._post()
        msg = ContactMessage.objects.get()
        self.assertFalse(msg.is_spam)
        self.assertEqual(msg.ip_address, "203.0.113.7")

    def test_trap_field_filled_is_dropped_but_looks_sent(self):
        response = self._post(website="http://spam.example")
        self.assertRedirects(response, CONTACT_URL, fetch_redirect_response=False)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_sent_too_fast_is_dropped(self):
        self._post(rendered_at=_rendered(seconds_ago=1))
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_missing_or_forged_timestamp_is_dropped(self):
        self._post(rendered_at="")
        self._post(rendered_at="1700000000")
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_sixth_message_in_an_hour_is_refused(self):
        for _ in range(spam.MAX_PER_HOUR):
            self._post()
            self.client.get(CONTACT_URL)  # show the "thanks" so the form comes back
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "try again later")
        self.assertEqual(ContactMessage.objects.count(), spam.MAX_PER_HOUR)

    def test_forwarded_ip_uses_the_address_nginx_added(self):
        self.client.post(CONTACT_URL, {**GOOD, "rendered_at": _rendered()},
                         HTTP_X_FORWARDED_FOR="1.1.1.1, 198.51.100.9", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(ContactMessage.objects.get().ip_address, "198.51.100.9")

    def test_many_links_filed_as_spam(self):
        self._post(message="see http://a.io http://b.io www.c.io")
        msg = ContactMessage.objects.get()
        self.assertTrue(msg.is_spam)
        self.assertEqual(msg.spam_reason, "links")

    @override_settings(SPAM_DETECTION_URL="https://spam.test")
    def test_detector_says_spam(self):
        with mock.patch.object(spam, "_post", return_value={"success": True, "is_spam": True, "spam_score": 0.9}):
            self._post()
        msg = ContactMessage.objects.get()
        self.assertTrue(msg.is_spam)
        self.assertEqual((msg.spam_reason, msg.spam_score), ("detector", 0.9))

    @override_settings(SPAM_DETECTION_URL="https://spam.test")
    def test_detector_down_keeps_message_in_inbox(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self._post()
        self.assertFalse(ContactMessage.objects.get().is_spam)


class DashboardSpamTest(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.create_superuser(email="owner@example.com", password="x", full_name="Owner")
        self.client.force_login(owner)
        self.ham = ContactMessage.objects.create(name="Ada", email="a@example.com", message="Real question")
        self.junk = ContactMessage.objects.create(name="Bot", email="b@example.com", message="Cheap pills",
                                                  is_spam=True, spam_reason="detector")

    def test_inbox_hides_spam_and_spam_tab_shows_it(self):
        inbox = self.client.get(reverse("dashboard:messages"))
        self.assertContains(inbox, "Real question")
        self.assertNotContains(inbox, "Cheap pills")
        self.assertContains(self.client.get(reverse("dashboard:messages") + "?show=spam"), "Cheap pills")

    def test_detail_offers_the_right_button(self):
        self.assertContains(self.client.get(reverse("dashboard:message_detail", args=[self.junk.pk])), "Not spam")
        self.assertNotContains(self.client.get(reverse("dashboard:message_detail", args=[self.ham.pk])), "Not spam")

    def test_spam_not_counted_as_unread(self):
        response = self.client.get(reverse("dashboard:messages"))
        self.assertEqual(response.context["unread_message_count"], 1)

    def test_marking_moves_message_and_teaches_detector(self):
        with mock.patch.object(spam, "report") as report:
            self.client.post(reverse("dashboard:message_mark_spam", args=[self.ham.pk]))
            self.client.post(reverse("dashboard:messages_bulk"), {"ids": [self.junk.pk], "action": "ham"})
        self.ham.refresh_from_db(); self.junk.refresh_from_db()
        self.assertEqual((self.ham.is_spam, self.ham.spam_reason), (True, "owner"))
        self.assertFalse(self.junk.is_spam)
        self.assertEqual([c.kwargs["is_spam"] for c in report.call_args_list], [True, False])


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
