"""
Tests for apps/booking/services/booking.py

Covers:
  - create_booking happy path
  - create_booking raises SlotUnavailableError when slot is full
  - create_booking raises SlotUnavailableError when no schedule exists
  - Concurrent booking race: two threads race for one spot, only one wins
"""
import datetime
import threading
import unittest

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.booking.models import (
    Booking,
    BookingSettings,
    Location,
    RecurringSchedule,
    SessionPricing,
    SessionType,
)
from apps.booking.services.booking import SlotUnavailableError, cancel_booking, confirm_booking, create_booking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_date_for_weekday(weekday: int, weeks_ahead: int = 2) -> datetime.date:
    """
    Return a date ``weeks_ahead`` weeks out that falls on ``weekday`` (0=Mon).
    Stays well inside the booking window (max_advance_days=60) and far enough
    past min_advance_hours=1.
    """
    today = timezone.now().date()
    days = (weekday - today.weekday()) % 7
    if days < 1:
        days += 7  # at least a week away
    return today + datetime.timedelta(days=days + (weeks_ahead - 1) * 7)


def _make_booking_fixtures(weekday: int = 2, max_capacity: int = 1):
    """
    Create the minimum model objects required for booking tests.
    Returns (session_type, location, future_date, start_time).
    """
    settings = BookingSettings.load()
    settings.max_advance_days = 60
    settings.min_advance_hours = 1
    settings.save()

    session_type = SessionType.objects.create(
        name="Private Lesson",
        slug=f"private-{weekday}",
        duration_minutes=60,
        max_participants=max_capacity,
        is_active=True,
    )
    location = Location.objects.create(
        name="Pool A",
        slug=f"pool-a-{weekday}",
        address="1 Test Lane, London",
        is_active=True,
    )
    SessionPricing.objects.create(
        session_type=session_type,
        location=location,
        price_pence=8000,
    )
    start_time = datetime.time(10, 0)
    RecurringSchedule.objects.create(
        session_type=session_type,
        location=location,
        day_of_week=weekday,
        start_time=start_time,
        end_time=datetime.time(11, 0),
        max_capacity=max_capacity,
        is_active=True,
    )
    future_date = _future_date_for_weekday(weekday)
    return session_type, location, future_date, start_time


# ---------------------------------------------------------------------------
# Functional tests (TestCase — fast, DB rolled back after each test)
# ---------------------------------------------------------------------------

class CreateBookingTest(TestCase):

    def setUp(self):
        self.st, self.loc, self.date, self.time = _make_booking_fixtures(weekday=2)

    def test_happy_path_creates_pending_booking(self):
        booking = create_booking(
            session_type_id=self.st.pk,
            location_id=self.loc.pk,
            date=self.date,
            start_time=self.time,
            client_name="Ada Lovelace",
            client_email="ada@example.com",
        )

        self.assertIsInstance(booking, Booking)
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.amount_pence, 8000)
        self.assertEqual(booking.client_email, "ada@example.com")
        self.assertEqual(Booking.objects.count(), 1)

    def test_raises_when_slot_is_full(self):
        """Once the one available spot is taken, a second attempt raises."""
        create_booking(
            session_type_id=self.st.pk,
            location_id=self.loc.pk,
            date=self.date,
            start_time=self.time,
            client_name="First",
            client_email="first@example.com",
        )

        with self.assertRaises(SlotUnavailableError):
            create_booking(
                session_type_id=self.st.pk,
                location_id=self.loc.pk,
                date=self.date,
                start_time=self.time,
                client_name="Second",
                client_email="second@example.com",
            )

        self.assertEqual(Booking.objects.count(), 1)

    def test_raises_when_no_schedule_exists_for_time(self):
        """A start_time with no schedule entry is always unavailable."""
        with self.assertRaises(SlotUnavailableError):
            create_booking(
                session_type_id=self.st.pk,
                location_id=self.loc.pk,
                date=self.date,
                start_time=datetime.time(14, 0),  # nothing scheduled at 14:00
                client_name="Ghost",
                client_email="ghost@example.com",
            )

    def test_cancelled_booking_frees_the_slot(self):
        """A cancelled booking does not count against capacity."""
        booking = create_booking(
            session_type_id=self.st.pk,
            location_id=self.loc.pk,
            date=self.date,
            start_time=self.time,
            client_name="Canceller",
            client_email="cancel@example.com",
        )
        booking.status = Booking.STATUS_CANCELLED
        booking.save(update_fields=["status", "updated_at"])

        # Slot is free again
        second = create_booking(
            session_type_id=self.st.pk,
            location_id=self.loc.pk,
            date=self.date,
            start_time=self.time,
            client_name="Replacer",
            client_email="replace@example.com",
        )
        self.assertIsInstance(second, Booking)

    def test_group_slot_allows_multiple_bookings_up_to_capacity(self):
        """A slot with max_capacity=2 accepts two bookings, rejects a third."""
        st2, loc2, date2, time2 = _make_booking_fixtures(weekday=3, max_capacity=2)

        create_booking(
            session_type_id=st2.pk, location_id=loc2.pk,
            date=date2, start_time=time2,
            client_name="One", client_email="one@example.com",
        )
        create_booking(
            session_type_id=st2.pk, location_id=loc2.pk,
            date=date2, start_time=time2,
            client_name="Two", client_email="two@example.com",
        )

        with self.assertRaises(SlotUnavailableError):
            create_booking(
                session_type_id=st2.pk, location_id=loc2.pk,
                date=date2, start_time=time2,
                client_name="Three", client_email="three@example.com",
            )

        self.assertEqual(
            Booking.objects.filter(session_type=st2).count(), 2
        )


# ---------------------------------------------------------------------------
# Concurrency test (TransactionTestCase — commits are real, visible to threads)
# ---------------------------------------------------------------------------

@unittest.skipIf(
    connection.vendor == "sqlite",
    "SQLite has no concurrent-write support — select_for_update() locking "
    "can only be verified on PostgreSQL.",
)
class ConcurrentBookingTest(TransactionTestCase):
    """
    Two threads race for the same single-capacity slot.
    Exactly one should succeed; the other should get SlotUnavailableError.

    Uses TransactionTestCase because threading requires actual DB commits —
    TestCase wraps everything in one transaction that threads can't see.
    The select_for_update() lock in create_booking serialises the two
    attempts so the capacity check is always consistent.

    Skipped on SQLite: SQLite is single-writer; the second thread hits
    'database table is locked' (OperationalError, not SlotUnavailableError)
    and the test produces a false failure. Switch to PostgreSQL to run this.
    """

    def setUp(self):
        self.st, self.loc, self.date, self.start = _make_booking_fixtures(weekday=4)

    def test_only_one_booking_created_under_concurrent_load(self):
        results = []
        result_lock = threading.Lock()
        barrier = threading.Barrier(2, timeout=10)

        def attempt(name, email):
            barrier.wait()  # both threads start at the same instant
            try:
                booking = create_booking(
                    session_type_id=self.st.pk,
                    location_id=self.loc.pk,
                    date=self.date,
                    start_time=self.start,
                    client_name=name,
                    client_email=email,
                )
                with result_lock:
                    results.append(("ok", booking.pk))
            except SlotUnavailableError:
                with result_lock:
                    results.append(("full", None))

        threads = [
            threading.Thread(target=attempt, args=("Alice", "alice@example.com")),
            threading.Thread(target=attempt, args=("Bob", "bob@example.com")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        successes = [r for r in results if r[0] == "ok"]
        failures = [r for r in results if r[0] == "full"]

        self.assertEqual(len(results), 2, "Both threads should have finished")
        self.assertEqual(len(successes), 1, "Exactly one booking should succeed")
        self.assertEqual(len(failures), 1, "Exactly one attempt should be rejected")
        self.assertEqual(Booking.objects.count(), 1, "Only one row in the DB")


# ---------------------------------------------------------------------------
# Fix 11 — htmx_calendar_panel loads BookingSettings once
# ---------------------------------------------------------------------------

class CalendarPanelSettingsTest(TestCase):
    """
    Fix 11 — htmx_calendar_panel had a redundant explicit BookingSettings.load()
    call after already loading it at the top of the function.  The view must
    honour max_advance_days from the single loaded instance.
    """

    def setUp(self):
        self.st, self.loc, _, _ = _make_booking_fixtures(weekday=2)

    def _calendar_url(self):
        from django.urls import reverse
        return reverse("booking:htmx_calendar", kwargs={"session_type_id": self.st.pk})

    def test_panel_returns_200_with_valid_session_type(self):
        response = self.client.get(self._calendar_url(), {"location_id": self.loc.pk})
        self.assertEqual(response.status_code, 200)

    def test_show_next_false_when_max_advance_days_is_one(self):
        """
        With max_advance_days=1, next month is always beyond the booking window
        so show_next must be False — proves settings.max_advance_days is used.
        """
        bs = BookingSettings.load()
        bs.max_advance_days = 1
        bs.save()

        response = self.client.get(self._calendar_url(), {"location_id": self.loc.pk})
        self.assertFalse(response.context["show_next"])

    def test_show_next_true_when_max_advance_days_is_large(self):
        """With max_advance_days=120, the next month should be reachable."""
        bs = BookingSettings.load()
        bs.max_advance_days = 120
        bs.save()

        response = self.client.get(self._calendar_url(), {"location_id": self.loc.pk})
        self.assertTrue(response.context["show_next"])


# ---------------------------------------------------------------------------
# Fix 12 — Booking.with_spots_taken() / spots_taken annotation cache
# ---------------------------------------------------------------------------

class WithSpotsTakenTest(TestCase):
    """
    Fix 12 — Booking.spots_taken was a property that fired one DB query per
    access, creating an N+1 on the bookings list.

    with_spots_taken() annotates each row with spots_taken_count via a
    correlated subquery.  The spots_taken property then reads from __dict__
    (zero extra queries when annotated) and falls back to a DB COUNT when not.
    """

    def setUp(self):
        self.st, self.loc, self.date, self.time = _make_booking_fixtures(
            weekday=0, max_capacity=4
        )

    def _book(self, email, status=Booking.STATUS_CONFIRMED):
        return Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name=email.split("@")[0],
            client_email=email,
            status=status,
            amount_pence=8000,
        )

    def test_annotation_count_is_correct(self):
        self._book("a@example.com")
        self._book("b@example.com")
        b = Booking.with_spots_taken().get(client_email="a@example.com")
        self.assertEqual(b.spots_taken, 2)

    def test_cancelled_bookings_excluded_from_count(self):
        b1 = self._book("a@example.com")
        self._book("b@example.com", status=Booking.STATUS_CANCELLED)
        b = Booking.with_spots_taken().get(pk=b1.pk)
        self.assertEqual(b.spots_taken, 1)

    def test_single_booking_counts_as_one(self):
        b = self._book("solo@example.com")
        annotated = Booking.with_spots_taken().get(pk=b.pk)
        self.assertEqual(annotated.spots_taken, 1)

    def test_spots_taken_reads_annotation_without_extra_db_query(self):
        """
        Once annotated, spots_taken must be served from __dict__ — no extra query.
        """
        self._book("a@example.com")
        self._book("b@example.com")
        b = Booking.with_spots_taken().get(client_email="a@example.com")
        self.assertIn("spots_taken_count", b.__dict__)

        with self.assertNumQueries(0):
            result = b.spots_taken

        self.assertEqual(result, 2)

    def test_spots_taken_fallback_queries_db_when_not_annotated(self):
        """Without annotation, spots_taken falls back to a DB query."""
        self._book("a@example.com")
        self._book("b@example.com")
        b = Booking.objects.get(client_email="a@example.com")
        self.assertNotIn("spots_taken_count", b.__dict__)
        # Fallback: result must still be correct
        self.assertEqual(b.spots_taken, 2)

    def test_annotation_not_polluted_across_different_slots(self):
        """
        Bookings for a different date must not inflate the count.
        """
        self._book("same-slot@example.com")
        # Book a different date on the same weekday (next week)
        other_date = self.date + datetime.timedelta(weeks=1)
        Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=other_date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="other",
            client_email="other@example.com",
            status=Booking.STATUS_CONFIRMED,
            amount_pence=8000,
        )
        b = Booking.with_spots_taken().get(client_email="same-slot@example.com")
        self.assertEqual(b.spots_taken, 1,
                         "Booking on a different date must not count towards this slot")


# ---------------------------------------------------------------------------
# Fix 5 — confirm_booking sends a confirmation email
# ---------------------------------------------------------------------------

class BookingConfirmationEmailTest(TestCase):
    """
    confirm_booking() must send one email to the client after marking the
    booking as confirmed.  The email must contain key booking details.
    """

    def setUp(self):
        self.st, self.loc, self.date, self.time = _make_booking_fixtures(weekday=1)

    def test_email_sent_on_confirm(self):
        from django.core import mail

        booking = Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="Test Client",
            client_email="client@example.com",
            status=Booking.STATUS_PENDING,
            amount_pence=8000,
        )

        confirm_booking(booking)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("client@example.com", email.to)
        self.assertIn("confirmed", email.subject.lower())

    def test_email_contains_booking_details(self):
        from django.core import mail

        booking = Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="Ada Lovelace",
            client_email="ada@example.com",
            status=Booking.STATUS_PENDING,
            amount_pence=8000,
        )

        confirm_booking(booking)

        body = mail.outbox[0].body
        # Template greets with client_first_name ("Ada"), not the full name
        self.assertIn("Ada", body)
        self.assertIn(self.st.name, body)
        self.assertIn(self.loc.name, body)
        self.assertIn(str(booking.reference), body)

    def test_email_failure_does_not_raise(self):
        """
        A broken SMTP config must never kill the booking confirmation —
        send_booking_confirmation in email.py swallows exceptions and logs them.
        """
        from unittest.mock import patch
        from apps.booking.services.booking import confirm_booking

        booking = Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="Safe Client",
            client_email="safe@example.com",
            status=Booking.STATUS_PENDING,
            amount_pence=8000,
        )

        # Patch the underlying send method inside the email service
        with patch(
            "apps.booking.services.email.EmailMultiAlternatives.send",
            side_effect=Exception("SMTP down"),
        ):
            # Must not raise
            result = confirm_booking(booking)

        self.assertEqual(result.status, Booking.STATUS_CONFIRMED)

    def test_booking_status_confirmed_even_when_email_is_sent(self):
        """confirm_booking returns the booking with STATUS_CONFIRMED."""
        from django.core import mail

        booking = Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="Verify",
            client_email="verify@example.com",
            status=Booking.STATUS_PENDING,
            amount_pence=8000,
        )

        result = confirm_booking(booking)

        self.assertEqual(result.status, Booking.STATUS_CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)


# ---------------------------------------------------------------------------
# Fix 9 — client booking cancellation view
# ---------------------------------------------------------------------------

class ClientBookingCancelTest(TestCase):
    """
    The cancel_booking_view must:
    - Cancel the booking when the logged-in user owns it and the session is far enough away
    - Reject the request if the booking belongs to someone else
    - Reject cancellation within the notice window
    - Reject already-cancelled bookings
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.user = User.objects.create_user(
            email="client@example.com",
            password="pass",
            full_name="Test Client",
            role="client",
        )
        self.st, self.loc, self.date, self.time = _make_booking_fixtures(weekday=3)

        # BookingSettings: 2-hour notice window
        bs = BookingSettings.load()
        bs.cancellation_hours = 2
        bs.save()

    def _make_booking(self, email="client@example.com", status=Booking.STATUS_CONFIRMED):
        return Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=self.date,
            start_time=self.time,
            end_time=datetime.time(11, 0),
            client_name="Test Client",
            client_email=email,
            status=status,
            amount_pence=8000,
        )

    def _cancel_url(self, booking):
        from django.urls import reverse
        return reverse("accounts:booking_cancel", args=[booking.reference])

    def test_cancel_succeeds_for_owner(self):
        """Logged-in user can cancel their own confirmed future booking."""
        self.client.force_login(self.user)
        booking = self._make_booking()

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, "/account/profile/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_cancel_rejected_for_other_user(self):
        """Cannot cancel a booking that belongs to someone else."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        other = User.objects.create_user(
            email="other@example.com",
            password="pass",
            full_name="Other Person",
            role="client",
        )
        self.client.force_login(other)
        booking = self._make_booking(email="client@example.com")

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, "/account/profile/")
        booking.refresh_from_db()
        # Must NOT be cancelled — wrong user
        self.assertNotEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_cancel_rejected_within_notice_window(self):
        """Cancellation within the notice window is refused."""
        from django.utils import timezone as tz
        self.client.force_login(self.user)

        # Create a booking starting in 1 hour — inside the 2-hour window
        now = tz.now()
        soon = now + datetime.timedelta(hours=1)
        booking = Booking.objects.create(
            session_type=self.st,
            location=self.loc,
            date=soon.date(),
            start_time=soon.time().replace(second=0, microsecond=0),
            end_time=(soon + datetime.timedelta(hours=1)).time().replace(second=0, microsecond=0),
            client_name="Test Client",
            client_email="client@example.com",
            status=Booking.STATUS_CONFIRMED,
            amount_pence=8000,
        )

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, "/account/profile/")
        booking.refresh_from_db()
        self.assertNotEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_cancel_already_cancelled_booking_rejected(self):
        """Cancelling an already-cancelled booking is a no-op (status check)."""
        self.client.force_login(self.user)
        booking = self._make_booking(status=Booking.STATUS_CANCELLED)

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, "/account/profile/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_get_request_not_allowed(self):
        """The cancel URL only accepts POST."""
        self.client.force_login(self.user)
        booking = self._make_booking()

        response = self.client.get(self._cancel_url(booking))

        self.assertEqual(response.status_code, 405)
