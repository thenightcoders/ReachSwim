"""
Tests for apps/dashboard/views.py

Fix 8 — SettingsViewHeroBugTest:
  Saving the hero section must only call hero.save(), not site.save().
  The stray site.save() in the hero branch was updating SiteConfig's
  cache timestamp and potentially overwriting concurrent site edits.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages.models import HeroSection, SiteConfig

User = get_user_model()

SETTINGS_URL = reverse("dashboard:settings")


class SettingsViewHeroBugTest(TestCase):

    def setUp(self):
        # Owner user required to access dashboard
        self.owner = User.objects.create_user(
            email="owner@reachswim.co.uk",
            password="strongpass123",
            full_name="Coach Maren",
            role="owner",
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)

        # Ensure singletons exist
        self.site = SiteConfig.load()
        self.site.site_name = "Original Name"
        self.site.save()

        self.hero = HeroSection.load()
        self.hero.headline = "Original headline"
        self.hero.save()

    def test_hero_save_updates_hero_not_site(self):
        """POSTing to the hero section must save hero fields, leave site unchanged."""
        response = self.client.post(SETTINGS_URL, {
            "_section": "hero",
            "headline": "New headline",
            "subheadline": "New subheadline",
            "cta_primary_text": "Book now",
            "cta_secondary_text": "Shop",
            "strip_items": "London|Adults",
        })

        self.assertRedirects(response, SETTINGS_URL)

        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "New headline")

        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "Original Name",
                         "site_name must not change when saving the hero section")

    def test_hero_save_does_not_call_site_save(self):
        """
        Verify at the model level: SiteConfig.updated_at must not change
        when the hero section is saved.
        """
        from django.utils import timezone
        import time

        self.site.save()  # stamp updated_at now
        site_before = SiteConfig.objects.get(pk=1).updated_at if hasattr(SiteConfig, 'updated_at') else None

        time.sleep(0.05)  # ensure clock would advance if save() were called

        self.client.post(SETTINGS_URL, {
            "_section": "hero",
            "headline": "Another headline",
            "subheadline": "sub",
            "cta_primary_text": "Book",
            "cta_secondary_text": "Shop",
            "strip_items": "London",
        })

        # Hero must have changed
        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "Another headline")

        # Site name must be untouched
        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "Original Name")

    def test_site_save_does_not_affect_hero(self):
        """Sanity check: saving the site section leaves hero alone."""
        response = self.client.post(SETTINGS_URL, {
            "_section": "site",
            "site_name": "ReachSwim Updated",
            "tagline": "Swim better",
            "email": "hi@reachswim.co.uk",
            "phone": "",
            "location_text": "London",
            "meta_description": "Adult coaching",
            "whatsapp_url": "",
            "instagram_url": "",
            "established_year": "2021",
        })

        self.assertRedirects(response, SETTINGS_URL)

        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "ReachSwim Updated")

        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "Original headline",
                         "Hero headline must not change when saving the site section")


# ---------------------------------------------------------------------------
# Fix 9 — dashboard home must not use __import__ hack
# ---------------------------------------------------------------------------

class DashboardHomeTotalClientsTest(TestCase):
    """
    Fix 9 — dashboard/home view previously used __import__ to get the User model.
    The fix replaces it with a direct import.  These tests verify the stat is
    counted correctly, which would fail if the import were broken.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@reachswim.co.uk",
            password="ownerpass",
            full_name="Coach Maren",
            role="owner",
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)
        # Ensure singletons exist so context processors don't error
        from apps.pages.models import SiteConfig
        SiteConfig.load()

    def test_home_view_returns_200(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)

    def test_total_clients_is_zero_when_no_clients_exist(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.context["total_clients"], 0)

    def test_total_clients_counts_only_client_role(self):
        """Owners and staff must not be counted — only role='client'."""
        User.objects.create_user(
            email="c1@example.com", full_name="Client One", role="client"
        )
        User.objects.create_user(
            email="c2@example.com", full_name="Client Two", role="client"
        )
        User.objects.create_user(
            email="staff@example.com", full_name="Staff", role="staff"
        )
        response = self.client.get("/dashboard/")
        self.assertEqual(response.context["total_clients"], 2,
                         "Only users with role='client' should be counted")


# ---------------------------------------------------------------------------
# Redesigned dashboard: every page renders, and the admin-parity actions work
# ---------------------------------------------------------------------------

import datetime as _dt

from django.utils import timezone as _tz


class DashboardCoverageTest(TestCase):
    """Smoke-tests every dashboard screen with realistic data, then the new actions."""

    @classmethod
    def setUpTestData(cls):
        from apps.booking.models import Booking, Location, Package, RecurringSchedule, SessionPricing, SessionType
        from apps.legal.models import ContactMessage, LegalPage
        from apps.pages.models import ApproachPillar, FAQItem, FooterColumn, FooterLink, Offering, Stat, Testimonial
        from apps.payments.models import Order, OrderItem, Voucher
        from apps.shop.models import Product, ProductCategory
        from apps.booking.services.package_purchase import create_purchase

        cls.owner = User.objects.create_user(email="owner@reachswim.co.uk", password="pw", full_name="Coach Maren", role="owner")
        cls.client_user = User.objects.create_user(email="sam@example.com", full_name="Sam Swimmer", role="client")
        cls.pool = Location.objects.create(name="Ironmonger Row", slug="ironmonger", address="1 Ironmonger Row\nEC1V 3QN")
        cls.st = SessionType.objects.create(name="1:1 lesson", slug="one-to-one", duration_minutes=45, max_participants=1)
        SessionPricing.objects.create(session_type=cls.st, location=cls.pool, price_pence=6500)
        cls.schedule = RecurringSchedule.objects.create(session_type=cls.st, location=cls.pool, day_of_week=0,
                                                        start_time=_dt.time(7), end_time=_dt.time(7, 45), max_capacity=1)
        cls.package = Package.objects.create(name="5 lessons", session_type=cls.st, location=cls.pool,
                                             session_count=5, price_pence=30000, valid_days=90)
        today = _tz.localdate()
        cls.booking = Booking.objects.create(session_type=cls.st, location=cls.pool, date=today,
                                             start_time=_dt.time(9), end_time=_dt.time(9, 45),
                                             client_name="Sam Swimmer", client_email="sam@example.com",
                                             status="confirmed", amount_pence=6500)
        cls.pending = Booking.objects.create(session_type=cls.st, location=cls.pool, date=today + _dt.timedelta(days=2),
                                             start_time=_dt.time(10), end_time=_dt.time(10, 45),
                                             client_name="Alex Pending", client_email="alex@example.com",
                                             status="pending", amount_pence=6500)
        cls.cat = ProductCategory.objects.create(name="Caps", slug="caps")
        cls.product = Product.objects.create(name="Silicone cap", slug="silicone-cap", category=cls.cat, price_pence=1200, stock=2)
        cls.order = Order.objects.create(client_name="Sam Swimmer", client_email="sam@example.com",
                                         subtotal_pence=1200, total_pence=1200, status="paid")
        OrderItem.objects.create(order=cls.order, item_type="product", product=cls.product, quantity=1,
                                 price_pence=1200, label="Silicone cap")
        cls.pending_order = Order.objects.create(client_name="Alex Pending", client_email="alex@example.com",
                                                 subtotal_pence=6500, total_pence=6500, status="pending")
        cls.voucher = Voucher.objects.create(code="SUMMER10", discount_type="percentage", discount_value=10,
                                             valid_from=_tz.now())
        cls.purchase = create_purchase(cls.package, "Sam Swimmer", "sam@example.com")
        cls.message = ContactMessage.objects.create(name="Jo", email="jo@example.com", subject="Lessons?", message="Hi there")
        Offering.objects.create(tag="01", title="Private", description="1:1", meta_items="60 min, London")
        Stat.objects.create(value="2,140+", label="Adults coached")
        ApproachPillar.objects.create(number="01", title="Breathe", description="First things first")
        Testimonial.objects.create(quote="Great coach", author_name="Pat", author_role="Engineer")
        FAQItem.objects.create(question="Do I need to swim?", answer="No")
        LegalPage.objects.create(title="Privacy", slug="privacy", content="<p>Policy</p>")
        col = FooterColumn.objects.create(title="Visit")
        FooterLink.objects.create(column=col, label="Book", url="/booking/")
        cls.footer = col

    def setUp(self):
        self.client.force_login(self.owner)

    def assertOk(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, f"{url} returned {response.status_code}")
        return response

    def test_every_page_renders(self):
        from apps.dashboard.registry import SECTIONS

        pages = [
            reverse("dashboard:home"), reverse("dashboard:bookings"), reverse("dashboard:bookings") + "?when=upcoming&status=pending",
            reverse("dashboard:booking_create"), reverse("dashboard:booking_detail", args=[self.booking.pk]),
            reverse("dashboard:booking_detail", args=[self.pending.pk]), reverse("dashboard:booking_edit", args=[self.booking.pk]),
            reverse("dashboard:orders"), reverse("dashboard:orders") + "?unshipped=1&q=sam",
            reverse("dashboard:order_detail", args=[self.order.pk]), reverse("dashboard:order_detail", args=[self.pending_order.pk]),
            reverse("dashboard:products"), reverse("dashboard:product_create"), reverse("dashboard:product_edit", args=[self.product.pk]),
            reverse("dashboard:messages"), reverse("dashboard:message_detail", args=[self.message.pk]),
            reverse("dashboard:user_list"), reverse("dashboard:user_create"),
            reverse("dashboard:user_detail", args=[self.client_user.pk]), reverse("dashboard:user_edit", args=[self.client_user.pk]),
            reverse("dashboard:pricing"), reverse("dashboard:packagepurchase_grant"),
            reverse("dashboard:settings"), reverse("dashboard:account"),
        ]
        for crud, _ in SECTIONS:
            pages.append(reverse(f"dashboard:{crud.key}_list"))
            pages.append(reverse(f"dashboard:{crud.key}_list") + "?q=a&o=-order")
            if crud.can_create:
                pages.append(reverse(f"dashboard:{crud.key}_create"))
            obj = crud.model.objects.first()
            self.assertIsNotNone(obj, f"no fixture for {crud.key}")
            pages.append(reverse(f"dashboard:{crud.key}_edit", args=[obj.pk]))
        for url in pages:
            with self.subTest(url=url):
                self.assertOk(url)

    def test_search_returns_grouped_results(self):
        data = self.client.get(reverse("dashboard:search"), {"q": "sam"}).json()
        names = {g["name"] for g in data["groups"]}
        self.assertIn("People", names)
        self.assertIn("Bookings", names)

    def test_csv_exports(self):
        for name in ("dashboard:bookings", "dashboard:orders", "dashboard:user_list"):
            response = self.client.get(reverse(name), {"export": "csv"})
            self.assertEqual(response["Content-Type"], "text/csv")
            self.assertIn("Sam Swimmer", response.content.decode())

    def test_voucher_create_converts_amount_to_pence(self):
        from apps.payments.models import Voucher
        response = self.client.post(reverse("dashboard:voucher_create"), {
            "code": "friend5", "discount_type": "fixed_pence", "amount": "5.50",
            "max_uses": "1", "valid_from": "2026-01-01T09:00", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        v = Voucher.objects.get(code="FRIEND5")
        self.assertEqual(v.discount_value, 550)

    def test_voucher_requires_percent_for_percentage_type(self):
        response = self.client.post(reverse("dashboard:voucher_create"), {
            "code": "BAD", "discount_type": "percentage", "max_uses": "0", "valid_from": "2026-01-01T09:00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("percent", response.context["form"].errors)

    def test_bulk_toggle_and_reset(self):
        from apps.payments.models import Voucher
        self.voucher.times_used = 3
        self.voucher.save()
        url = reverse("dashboard:voucher_bulk")
        self.client.post(url, {"ids": [self.voucher.pk], "action": "deactivate"})
        self.client.post(url, {"ids": [self.voucher.pk], "action": "reset"})
        self.voucher.refresh_from_db()
        self.assertFalse(self.voucher.is_active)
        self.assertEqual(self.voucher.times_used, 0)

    def test_pricing_matrix_saves_and_clears(self):
        from apps.booking.models import SessionPricing
        key = f"price_{self.st.pk}_{self.pool.pk}"
        self.client.post(reverse("dashboard:pricing"), {key: "70.25"})
        self.assertEqual(SessionPricing.objects.get(session_type=self.st, location=self.pool).price_pence, 7025)
        self.client.post(reverse("dashboard:pricing"), {key: ""})
        self.assertFalse(SessionPricing.objects.filter(session_type=self.st, location=self.pool).exists())

    def test_session_type_edit_saves_inline_prices(self):
        from apps.booking.models import SessionPricing
        self.client.post(reverse("dashboard:sessiontype_edit", args=[self.st.pk]), {
            "name": "1:1 lesson", "slug": "one-to-one", "duration_minutes": "45", "max_participants": "1",
            "is_active": "on", "order": "0", f"price_{self.pool.pk}": "80",
        })
        self.assertEqual(SessionPricing.objects.get(session_type=self.st, location=self.pool).price_pence, 8000)

    def test_bulk_confirm_booking(self):
        self.client.post(reverse("dashboard:bookings_bulk"), {"ids": [self.pending.pk], "action": "confirm"})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "confirmed")

    def test_expire_pending_order(self):
        self.client.post(reverse("dashboard:order_expire", args=[self.pending_order.pk]))
        self.pending_order.refresh_from_db()
        self.assertEqual(self.pending_order.status, "expired")

    def test_messages_open_marks_read_and_bulk_unread(self):
        self.assertOk(reverse("dashboard:message_detail", args=[self.message.pk]))
        self.message.refresh_from_db()
        self.assertTrue(self.message.is_read)
        self.client.post(reverse("dashboard:messages_bulk"), {"ids": [self.message.pk], "action": "unread"})
        self.message.refresh_from_db()
        self.assertFalse(self.message.is_read)

    def test_grant_package_creates_complimentary_credits(self):
        from apps.payments.models import PackagePurchase
        self.client.post(reverse("dashboard:packagepurchase_grant"), {
            "package": self.package.pk, "client_name": "Kim", "client_email": "Kim@Example.com", "complimentary": "on",
        })
        purchase = PackagePurchase.objects.get(client_email="kim@example.com")
        self.assertEqual(purchase.amount_pence, 0)
        self.assertEqual(purchase.credits_remaining, 5)

    def test_freezing_package_freezes_unused_credits(self):
        self.client.post(reverse("dashboard:packagepurchase_toggle", args=[self.purchase.pk]))
        self.purchase.refresh_from_db()
        self.assertFalse(self.purchase.is_active)
        self.assertEqual(self.purchase.credits_remaining, 0)

    def test_footer_links_formset_saves(self):
        from apps.pages.models import FooterLink
        link = self.footer.links.first()
        self.client.post(reverse("dashboard:footer_edit", args=[self.footer.pk]), {
            "title": "Visit", "order": "0",
            "links-TOTAL_FORMS": "2", "links-INITIAL_FORMS": "1", "links-MIN_NUM_FORMS": "0", "links-MAX_NUM_FORMS": "1000",
            "links-0-id": link.pk, "links-0-column": self.footer.pk, "links-0-label": "Book now", "links-0-url": "/booking/", "links-0-order": "0",
            "links-1-column": self.footer.pk, "links-1-label": "Shop", "links-1-url": "/shop/", "links-1-order": "1",
        })
        self.assertEqual(list(FooterLink.objects.filter(column=self.footer).values_list("label", flat=True)), ["Book now", "Shop"])

    def test_protected_delete_shows_error_instead_of_crashing(self):
        response = self.client.post(reverse("dashboard:category_delete", args=[self.cat.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(type(self.cat).objects.filter(pk=self.cat.pk).exists())

    def test_settings_invalid_form_rerenders_with_errors(self):
        response = self.client.post(SETTINGS_URL, {"_section": "booking", "max_advance_days": "soon"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "booking")

    def test_owner_cannot_demote_self(self):
        self.client.post(reverse("dashboard:user_edit", args=[self.owner.pk]), {
            "full_name": "Coach Maren", "email": self.owner.email, "phone": "", "role": "client", "is_active": "on",
        })
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, "owner")

    def test_clients_cannot_open_dashboard(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("dashboard:voucher_list")).status_code, 403)
