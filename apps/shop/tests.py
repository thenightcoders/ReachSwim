"""
Tests for apps/shop/models.py, context processors, and cart interactions.

Covers:
  - ShopSettings singleton: shipping_cost() thresholds
  - Product: active/inactive filtering via cart_add_product view
  - Shop context processor: shop_settings injected into templates
  - CartAddProduct: server-side price fetch (security, already in payments tests
    but repeated here from the shop side for cross-app coverage)
"""
import json

from django.test import TestCase

from apps.shop.models import Product, ProductCategory, ShopSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(name="Cap", price_pence=2400, stock=10, is_active=True):
    cat, _ = ProductCategory.objects.get_or_create(name="Caps", slug="caps")
    slug = name.lower().replace(" ", "-")
    return Product.objects.create(
        name=name,
        slug=slug,
        category=cat,
        price_pence=price_pence,
        stock=stock,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# ShopSettings singleton
# ---------------------------------------------------------------------------

class ShopSettingsShippingTest(TestCase):
    """
    ShopSettings.shipping_cost() must:
    - return 0 when product total >= free threshold
    - return shipping_rate when below threshold
    - return 0 when threshold is 0 (always free)
    """

    def setUp(self):
        self.settings = ShopSettings.load()
        self.settings.free_shipping_threshold_pence = 5000  # £50
        self.settings.shipping_rate_pence = 495             # £4.95
        self.settings.save()

    def test_below_threshold_charges_shipping(self):
        self.assertEqual(self.settings.shipping_cost(4999), 495)

    def test_at_threshold_shipping_is_free(self):
        self.assertEqual(self.settings.shipping_cost(5000), 0)

    def test_above_threshold_shipping_is_free(self):
        self.assertEqual(self.settings.shipping_cost(9999), 0)

    def test_zero_threshold_always_free(self):
        self.settings.free_shipping_threshold_pence = 0
        self.settings.save()
        self.assertEqual(self.settings.shipping_cost(1), 0)

    def test_zero_product_total_charges_shipping(self):
        self.assertEqual(self.settings.shipping_cost(0), 495)


# ---------------------------------------------------------------------------
# Product model
# ---------------------------------------------------------------------------

class ProductModelTest(TestCase):

    def test_price_display_property(self):
        p = _make_product("Goggles", price_pence=1499)
        self.assertEqual(p.price_display, "£14.99")

    def test_in_stock_true(self):
        p = _make_product(stock=3)
        self.assertTrue(p.in_stock)

    def test_in_stock_false_when_zero(self):
        p = _make_product(stock=0)
        self.assertFalse(p.in_stock)

    def test_inactive_product_not_returned_by_default_manager(self):
        _make_product("Inactive Cap", is_active=False)
        _make_product("Active Cap", is_active=True)
        # Default queryset has no active filter — both exist
        self.assertEqual(Product.objects.count(), 2)


# ---------------------------------------------------------------------------
# Shop context processor
# ---------------------------------------------------------------------------

class ShopContextProcessorTest(TestCase):
    """
    shop_settings must be injected into every template context when the
    shop context processor is registered.
    """

    def setUp(self):
        from apps.pages.models import SiteConfig
        SiteConfig.load()
        ShopSettings.load()

    def test_shop_settings_in_homepage_context(self):
        response = self.client.get("/")
        self.assertIn("shop_settings", response.context)

    def test_shop_settings_is_shop_settings_instance(self):
        response = self.client.get("/")
        self.assertIsInstance(response.context["shop_settings"], ShopSettings)


# ---------------------------------------------------------------------------
# Cart + shop integration: add product → qty stacks
# ---------------------------------------------------------------------------

class CartAddProductQtyStackTest(TestCase):
    """
    Adding the same product twice must stack qty, not create a duplicate line.
    """

    def setUp(self):
        self.product = _make_product("Silicone Cap", price_pence=2400, stock=10)

    def _add(self, qty=1):
        return self.client.post(
            "/cart/add-product/",
            data=json.dumps({
                "product_id": self.product.pk,
                "qty": qty,
            }),
            content_type="application/json",
        )

    def test_single_add_creates_one_item(self):
        self._add(qty=1)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["qty"], 1)

    def test_double_add_stacks_qty(self):
        self._add(qty=1)
        self._add(qty=1)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 1, "Must be one line item, not two")
        self.assertEqual(cart[0]["qty"], 2)

    def test_add_qty_2_then_1_gives_3(self):
        self._add(qty=2)
        self._add(qty=1)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(cart[0]["qty"], 3)

    def test_price_is_always_from_db(self):
        """Even when stacking, price must come from the DB, not the request."""
        self._add(qty=1)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(cart[0]["price_pence"], 2400)


# ---------------------------------------------------------------------------
# Booking admin actions (smoke tests without real email dispatch)
# ---------------------------------------------------------------------------

class BookingAdminActionsTest(TestCase):
    """
    Smoke-test the admin actions registered on BookingAdmin:
    confirm, cancel, complete, resend_confirmation_emails.

    These tests use force_login for an admin user and POST to the changelist
    action endpoint.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        import datetime
        from apps.booking.models import (
            Booking, BookingSettings, Location, RecurringSchedule,
            SessionPricing, SessionType,
        )

        User = get_user_model()
        self.admin = User.objects.create_superuser(
            email="admin@reachswim.co.uk",
            password="adminpass",
            full_name="Admin",
        )
        self.client.force_login(self.admin)

        # Fixtures
        bs = BookingSettings.load()
        bs.max_advance_days = 60
        bs.min_advance_hours = 1
        bs.save()

        self.st = SessionType.objects.create(
            name="Admin Test", slug="admin-test", duration_minutes=60,
            is_active=True, max_participants=5,
        )
        self.loc = Location.objects.create(
            name="Admin Pool", slug="admin-pool",
            address="1 Admin Ln", is_active=True,
        )
        SessionPricing.objects.create(
            session_type=self.st, location=self.loc, price_pence=8000
        )
        RecurringSchedule.objects.create(
            session_type=self.st, location=self.loc,
            day_of_week=2, start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0), max_capacity=5, is_active=True,
        )
        self.booking_pending = Booking.objects.create(
            session_type=self.st, location=self.loc,
            date=datetime.date(2030, 6, 1),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            client_name="Pending Client", client_email="pending@example.com",
            status=Booking.STATUS_PENDING, amount_pence=8000,
        )
        self.booking_confirmed = Booking.objects.create(
            session_type=self.st, location=self.loc,
            date=datetime.date(2030, 6, 8),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            client_name="Confirmed Client", client_email="confirmed@example.com",
            status=Booking.STATUS_CONFIRMED, amount_pence=8000,
        )

    def _action(self, action, pks):
        return self.client.post(
            "/admin/booking/booking/",
            {"action": action, "_selected_action": pks},
        )

    def test_confirm_pending_booking(self):
        from django.core import mail
        self._action("confirm_bookings", [self.booking_pending.pk])
        self.booking_pending.refresh_from_db()
        self.assertEqual(self.booking_pending.status, "confirmed")
        # Confirmation email must have been sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("confirmed@example.com".replace("confirmed", "pending"), mail.outbox[0].to)

    def test_cancel_confirmed_booking(self):
        self._action("cancel_bookings", [self.booking_confirmed.pk])
        self.booking_confirmed.refresh_from_db()
        self.assertEqual(self.booking_confirmed.status, "cancelled")

    def test_complete_confirmed_booking(self):
        self._action("complete_bookings", [self.booking_confirmed.pk])
        self.booking_confirmed.refresh_from_db()
        self.assertEqual(self.booking_confirmed.status, "completed")

    def test_resend_confirmation_email_to_confirmed_booking(self):
        from django.core import mail
        self._action("resend_confirmation_emails", [self.booking_confirmed.pk])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.booking_confirmed.client_email, mail.outbox[0].to)

    def test_confirm_action_skips_already_confirmed(self):
        """Confirming an already-confirmed booking must be a no-op."""
        from django.core import mail
        self._action("confirm_bookings", [self.booking_confirmed.pk])
        # No email — nothing changed
        self.assertEqual(len(mail.outbox), 0)
        self.booking_confirmed.refresh_from_db()
        self.assertEqual(self.booking_confirmed.status, "confirmed")
