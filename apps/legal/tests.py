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

from datetime import timedelta

from django.core import mail, signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import tasks
from .models import BannedSender, ContactConfig, ContactMessage, LegalPage, SpamCheckStatus
from .services import contact_email, spam


CONTACT_URL = reverse("legal:contact")


def _rendered(seconds_ago=10):
    """A form timestamp as if the page was shown ``seconds_ago``."""
    return signing.dumps(time.time() - seconds_ago, salt=spam.TIMESTAMP_SALT)


# ---------------------------------------------------------------------------
# ContactMessage submission
# ---------------------------------------------------------------------------

@override_settings(SPAM_DETECTION_URL="", USE_DJANGO_Q_FOR_EMAILS=False)
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
API = "https://spam.test"


class FakeApi:
    """
    Stands in for spam._request. ``answers`` maps a path to (status, body), or
    to a function of the payload returning one. Every call is kept in ``calls``.
    """

    def __init__(self, **answers):
        self.answers = {"/health/": (200, {"status": "ok"}), **{k.replace("_", "/"): v for k, v in answers.items()}}
        self.calls = []

    def __call__(self, path, payload=None, *, use_key=True):
        self.calls.append((path, payload))
        answer = self.answers.get(path, (0, None))
        return answer(payload) if callable(answer) else answer

    def paths(self):
        return [p for p, _ in self.calls]


def _verdict(is_spam, score):
    return lambda payload: (200, {"success": True, "is_spam": is_spam, "spam_score": score,
                                  "external_id": payload.get("external_id")})


def _owner():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_superuser(email="owner@example.com", password="x", full_name="Owner")


@override_settings(SPAM_DETECTION_URL="", USE_DJANGO_Q_FOR_EMAILS=False)
class ContactSpamTest(TestCase):

    def setUp(self):
        ContactConfig.load()

    def _post(self, **overrides):
        data = {**GOOD, "rendered_at": _rendered(), **overrides}
        return self.client.post(CONTACT_URL, data, REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="TestBrowser/1.0")

    def test_check_switched_off_goes_straight_to_inbox(self):
        self._post()
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.folder, "inbox")
        self.assertEqual((msg.ip_address, msg.user_agent), ("203.0.113.7", "TestBrowser/1.0"))

    @override_settings(SPAM_DETECTION_URL=API)
    def test_new_message_waits_in_quarantine_and_is_queued(self):
        with mock.patch("django_q.tasks.async_task") as queue:
            self._post()
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.folder, "quarantine")
        queue.assert_called_once_with("apps.legal.tasks.check_message", msg.pk)
        self.assertEqual(len(mail.outbox), 0)  # no thank-you until it's cleared

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

    def test_three_links_filed_as_spam(self):
        self._post(message="see http://a.io http://b.io www.c.io")
        msg = ContactMessage.objects.get()
        self.assertEqual((msg.folder, msg.spam_reason), ("spam", "links"))

    @override_settings(SITE_URL="https://reachswim.co.uk")
    def test_links_to_this_website_dont_count(self):
        self._post(message="booked https://reachswim.co.uk/book/ and www.reachswim.co.uk/faq, "
                           "saw http://a.io and https://b.io")
        self.assertEqual(ContactMessage.objects.get().folder, "inbox")

    @override_settings(SPAM_DETECTION_URL=API)
    def test_banned_sender_goes_to_spam_but_is_still_checked(self):
        BannedSender.objects.create(email="Ada@Example.com")
        with mock.patch("django_q.tasks.async_task") as queue:
            self._post()
        msg = ContactMessage.objects.get()
        self.assertEqual((msg.folder, msg.spam_reason), ("spam", "banned"))
        queue.assert_called_once_with("apps.legal.tasks.check_message", msg.pk)


@override_settings(SPAM_DETECTION_URL="", USE_DJANGO_Q_FOR_EMAILS=False)
class ContactEmailTest(TestCase):

    def setUp(self):
        ContactConfig.load()
        _owner()

    def test_inbox_message_thanks_sender_and_tells_owner_in_bcc(self):
        self.client.post(CONTACT_URL, {**GOOD, "rendered_at": _rendered()})
        thanks, heads_up = mail.outbox
        self.assertEqual((thanks.to, thanks.bcc), (["ada@example.com"], []))
        self.assertNotIn("Do you teach beginners?", thanks.body)  # never echo the visitor's text
        self.assertEqual(heads_up.to, [])
        self.assertIn("owner@example.com", heads_up.bcc)
        self.assertEqual(heads_up.reply_to, ["ada@example.com"])
        self.assertIn("Do you teach beginners?", heads_up.body)

    def test_spam_sends_nothing(self):
        self.client.post(CONTACT_URL, {**GOOD, "message": "http://a.io http://b.io http://c.io", "rendered_at": _rendered()})
        self.assertEqual(mail.outbox, [])

    def test_notified_only_once(self):
        msg = ContactMessage.objects.create(name="Ada", email="ada@example.com", message="Hi")
        contact_email.notify(msg)
        contact_email.notify(msg)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(USE_DJANGO_Q_FOR_EMAILS=True)
    def test_emails_go_through_django_q_when_switched_on(self):
        with mock.patch("django_q.tasks.async_task") as queue:
            self.client.post(CONTACT_URL, {**GOOD, "rendered_at": _rendered()})
        self.assertEqual(mail.outbox, [])
        self.assertEqual([c.args[0] for c in queue.call_args_list], ["apps.pages.mail.deliver"] * 2)


@override_settings(SPAM_DETECTION_URL=API, SPAM_DETECTION_API_KEY="", USE_DJANGO_Q_FOR_EMAILS=False)
class SpamCheckTest(TestCase):

    def setUp(self):
        ContactConfig.load()

    def _waiting(self, **kw):
        return ContactMessage.objects.create(**{"name": "Ada", "email": "ada@example.com",
                                                "message": "Hello", "quarantined": True, **kw})

    def test_clean_message_moves_to_inbox_and_is_notified(self):
        msg = self._waiting(ip_address="203.0.113.7", user_agent="TestBrowser/1.0")
        api = FakeApi(**{"/v2/check-spam/": _verdict(False, 0.1)})
        with mock.patch.object(spam, "_request", api):
            tasks.check_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual((msg.folder, msg.spam_score, msg.check_attempts), ("inbox", 0.1, 1))
        self.assertIsNotNone(msg.notified_at)
        self.assertEqual(api.paths(), ["/health/", "/v2/check-spam/"])
        sent = api.calls[1][1]
        self.assertEqual((sent["ip"], sent["user_agent"], sent["external_id"]),
                         ("203.0.113.7", "TestBrowser/1.0", f"contact-{msg.pk}"))

    def test_spam_verdict_moves_to_spam_without_email(self):
        msg = self._waiting()
        with mock.patch.object(spam, "_request", FakeApi(**{"/v2/check-spam/": _verdict(True, 0.9)})):
            tasks.check_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual((msg.folder, msg.spam_reason, msg.spam_score), ("spam", "detector", 0.9))
        self.assertEqual(mail.outbox, [])

    def test_api_down_keeps_message_and_remembers(self):
        msg = self._waiting()
        api = FakeApi(**{"/health/": (503, {"status": "unhealthy", "checks": {"detector": "error", "database": "ok"}})})
        with mock.patch.object(spam, "_request", api):
            run = spam.check([msg])
        msg.refresh_from_db()
        self.assertEqual((run.api_ok, run.waiting, msg.folder), (False, 1, "quarantine"))
        self.assertEqual(api.paths(), ["/health/"])  # one request, not one per message
        status = SpamCheckStatus.load()
        self.assertIs(status.api_ok, False)
        self.assertIn("detector", status.last_error)

    def test_busy_api_stops_early(self):
        first, second = self._waiting(), self._waiting()
        api = FakeApi(**{"/v2/check-spam/": (429, None)})
        with mock.patch.object(spam, "_request", api):
            run = spam.check([first, second])
        self.assertTrue(run.busy)
        self.assertEqual(api.paths().count("/v2/check-spam/"), 1)
        self.assertEqual(ContactMessage.objects.quarantine().count(), 2)

    def test_spam_message_is_scored_but_stays_in_spam(self):
        msg = self._waiting(quarantined=False, is_spam=True, spam_reason="banned")
        with mock.patch.object(spam, "_request", FakeApi(**{"/v2/check-spam/": _verdict(False, 0.2)})):
            tasks.sweep()
        msg.refresh_from_db()
        self.assertEqual((msg.folder, msg.spam_reason, msg.spam_score), ("spam", "banned", 0.2))

    def test_owner_filing_during_check_wins(self):
        msg = self._waiting()
        def answer(payload):
            ContactMessage.objects.filter(pk=msg.pk).update(quarantined=False, is_spam=True, spam_reason="owner")
            return _verdict(False, 0.1)(payload)
        with mock.patch.object(spam, "_request", FakeApi(**{"/v2/check-spam/": answer})):
            spam.check([msg])
        msg.refresh_from_db()
        self.assertEqual((msg.folder, msg.spam_reason), ("spam", "owner"))

    @override_settings(SPAM_DETECTION_API_KEY="key")
    def test_with_a_key_uses_bulk(self):
        msgs = [self._waiting(), self._waiting()]
        bulk = lambda payload: (200, {"results": [{**_verdict(i == 0, 0.5)(item)[1], "index": i}
                                                  for i, item in enumerate(payload["items"])]})
        api = FakeApi(**{"/v2/check-spam/bulk/": bulk})
        with mock.patch.object(spam, "_request", api):
            spam.check(msgs)
        self.assertEqual(api.paths(), ["/health/", "/v2/check-spam/bulk/"])
        self.assertEqual([ContactMessage.objects.get(pk=m.pk).folder for m in msgs], ["spam", "inbox"])

    @override_settings(SPAM_DETECTION_API_KEY="wrong")
    def test_refused_key_falls_back_to_one_by_one(self):
        msg = self._waiting()
        api = FakeApi(**{"/v2/check-spam/bulk/": (403, None), "/v2/check-spam/": _verdict(False, 0.1)})
        with mock.patch.object(spam, "_request", api):
            spam.check([msg])
        self.assertEqual(api.paths(), ["/health/", "/v2/check-spam/bulk/", "/v2/check-spam/"])
        self.assertEqual(ContactMessage.objects.get(pk=msg.pk).folder, "inbox")

    def test_pile_up_alerts_owner_once_a_day(self):
        _owner()
        for _ in range(spam.ALERT_COUNT):
            self._waiting()
        self.assertTrue(spam.maybe_alert())
        self.assertFalse(spam.maybe_alert())
        alert, = mail.outbox
        self.assertIn("waiting for the spam check", alert.subject)
        self.assertIn("owner@example.com", alert.bcc)

    def test_one_old_message_alerts_too(self):
        _owner()
        msg = self._waiting()
        ContactMessage.objects.filter(pk=msg.pk).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertTrue(spam.maybe_alert())

    def test_a_few_fresh_messages_dont_alert(self):
        _owner()
        self._waiting()
        self.assertFalse(spam.maybe_alert())

    def test_report_without_key_goes_one_by_one(self):
        msgs = [self._waiting(), self._waiting()]
        api = FakeApi(**{"/v2/suggestion/": (200, {"success": True})})
        with mock.patch.object(spam, "_request", api):
            spam.report(msgs, is_spam=True)
        self.assertEqual(api.paths(), ["/v2/suggestion/"] * 2)
        self.assertEqual(api.calls[0][1]["external_id"], f"contact-{msgs[0].pk}")

    @override_settings(SPAM_DETECTION_API_KEY="key")
    def test_report_with_key_uses_bulk(self):
        api = FakeApi(**{"/v2/suggestion/bulk/": (200, {"success": True})})
        with mock.patch.object(spam, "_request", api):
            spam.report([self._waiting(), self._waiting()], is_spam=False)
        self.assertEqual(api.paths(), ["/v2/suggestion/bulk/"])


@override_settings(SPAM_DETECTION_URL=API, USE_DJANGO_Q_FOR_EMAILS=False)
class DashboardSpamTest(TestCase):

    def setUp(self):
        self.client.force_login(_owner())
        self.ham = ContactMessage.objects.create(name="Ada", email="a@example.com", message="Real question")
        self.junk = ContactMessage.objects.create(name="Bot", email="b@example.com", message="Cheap pills",
                                                  is_spam=True, spam_reason="detector")
        queue = mock.patch("django_q.tasks.async_task")
        self.queue = queue.start()
        self.addCleanup(queue.stop)

    def test_inbox_hides_spam_and_spam_tab_shows_it(self):
        inbox = self.client.get(reverse("dashboard:messages"))
        self.assertContains(inbox, "Real question")
        self.assertNotContains(inbox, "Cheap pills")
        self.assertContains(self.client.get(reverse("dashboard:messages") + "?show=spam"), "Cheap pills")

    def test_quarantine_tab_only_shows_when_something_waits(self):
        self.assertNotContains(self.client.get(reverse("dashboard:messages")), "Quarantine")
        ContactMessage.objects.create(name="New", email="n@example.com", message="Pending one", quarantined=True)
        inbox = self.client.get(reverse("dashboard:messages"))
        self.assertContains(inbox, "Quarantine")
        self.assertContains(inbox, "1 message waiting for the spam check")
        self.assertNotContains(inbox, "Pending one")
        self.assertContains(self.client.get(reverse("dashboard:messages") + "?show=quarantine"), "Pending one")

    def test_banner_everywhere_when_api_is_down(self):
        ContactMessage.objects.create(name="New", email="n@example.com", message="Pending", quarantined=True)
        status = SpamCheckStatus.load()
        status.api_ok = False
        status.save()
        self.assertContains(self.client.get(reverse("dashboard:home")), "The spam check service is down")

    def test_detail_offers_the_right_button(self):
        self.assertContains(self.client.get(reverse("dashboard:message_detail", args=[self.junk.pk])), "Not spam")
        self.assertNotContains(self.client.get(reverse("dashboard:message_detail", args=[self.ham.pk])), "Not spam")

    def test_spam_not_counted_as_unread(self):
        response = self.client.get(reverse("dashboard:messages"))
        self.assertEqual(response.context["unread_message_count"], 1)

    def test_marking_moves_message_and_teaches_detector(self):
        self.client.post(reverse("dashboard:message_mark_spam", args=[self.ham.pk]))
        self.client.post(reverse("dashboard:messages_bulk"), {"ids": [self.junk.pk], "action": "ham"})
        self.ham.refresh_from_db(); self.junk.refresh_from_db()
        self.assertEqual((self.ham.folder, self.ham.spam_reason), ("spam", "owner"))
        self.assertEqual(self.junk.folder, "inbox")
        reports = [c.args[1:] for c in self.queue.call_args_list if c.args[0] == "apps.legal.tasks.report"]
        self.assertEqual(reports, [([self.ham.pk], True), ([self.junk.pk], False)])

    def test_releasing_from_quarantine_thanks_the_sender(self):
        waiting = ContactMessage.objects.create(name="New", email="n@example.com", message="Hi", quarantined=True)
        self.client.post(reverse("dashboard:messages_bulk"), {"ids": [waiting.pk], "action": "ham"})
        self.assertEqual(ContactMessage.objects.get(pk=waiting.pk).folder, "inbox")
        self.assertIn(["n@example.com"], [m.to for m in mail.outbox])

    def test_ban_moves_every_message_from_that_address(self):
        older = ContactMessage.objects.create(name="Ada", email="A@Example.com", message="Older one")
        response = self.client.post(reverse("dashboard:messages_bulk"), {"ids": [self.ham.pk], "action": "ban"}, follow=True)
        self.assertContains(response, "2 message(s) moved to Spam")
        for m in (self.ham, older):
            m.refresh_from_db()
            self.assertEqual((m.folder, m.spam_reason), ("spam", "banned"))
        self.assertTrue(BannedSender.is_banned("a@EXAMPLE.com"))

    def test_unban_from_detail(self):
        BannedSender.objects.create(email="a@example.com")
        self.client.post(reverse("dashboard:message_ban", args=[self.ham.pk]), {"state": "unban"})
        self.assertFalse(BannedSender.is_banned("a@example.com"))

    def test_check_again_reports_when_api_is_down(self):
        waiting = ContactMessage.objects.create(name="New", email="n@example.com", message="Hi", quarantined=True)
        with mock.patch.object(spam, "_request", FakeApi(**{"/health/": (0, None)})):
            response = self.client.post(reverse("dashboard:messages_bulk"),
                                        {"ids": [waiting.pk], "action": "check"}, follow=True)
        self.assertContains(response, "service is down")
        self.assertEqual(ContactMessage.objects.get(pk=waiting.pk).folder, "quarantine")


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
