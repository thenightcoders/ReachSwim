"""
Tests for payment-layer fixes.

Fix 1 — CartAddPriceSecurityTest:
  cart_add must look up price_pence from SessionPricing, never trust
  the client-supplied value in the request body.

Fix 3 — StockDeductionTest:
  confirm_order must deduct stock atomically (F() expression + stock__gte
  guard), never read-modify-write, never go below zero.
"""
import json

from django.test import TestCase

from apps.booking.models import Location, SessionPricing, SessionType
from apps.payments.interfaces import PaymentEvent
from apps.payments.models import Order, OrderItem
from apps.payments.services.checkout import confirm_order
from apps.shop.models import Product, ProductCategory


# ---------------------------------------------------------------------------
# Fix 1: Price manipulation prevention
# ---------------------------------------------------------------------------

class CartAddPriceSecurityTest(TestCase):
    """
    The cart_add view must ignore request body price_pence and fetch the
    authoritative price from SessionPricing.  A client that crafts a request
    with price_pence=1 must not be able to book an £80 session for 1p.
    """

    def setUp(self):
        self.session_type = SessionType.objects.create(
            name="Private Lesson",
            slug="private",
            duration_minutes=60,
            is_active=True,
        )
        self.location = Location.objects.create(
            name="Pool A",
            slug="pool-a",
            address="1 Test Lane, London",
            is_active=True,
        )
        SessionPricing.objects.create(
            session_type=self.session_type,
            location=self.location,
            price_pence=8000,  # £80 — the canonical price
        )

    def _post_add(self, *, price_pence: int, session_type_id=None, location_id=None):
        return self.client.post(
            "/cart/add/",
            data=json.dumps({
                "session_type_id": session_type_id or self.session_type.pk,
                "location_id": location_id or self.location.pk,
                "date": "2027-06-01",
                "start_time": "10:00",
                "end_time": "11:00",
                "price_pence": price_pence,
                "label": "Private Lesson @ Pool A",
            }),
            content_type="application/json",
        )

    def test_tampered_low_price_is_ignored(self):
        """Sending price_pence=1 stores the DB price (8000), not 1."""
        response = self._post_add(price_pence=1)

        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["price_pence"], 8000)

    def test_tampered_zero_price_is_ignored(self):
        """Sending price_pence=0 (free session) stores the DB price."""
        response = self._post_add(price_pence=0)

        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(cart[0]["price_pence"], 8000)

    def test_even_correct_client_price_is_re_fetched(self):
        """
        Even if the client sends the right price, the view must still
        look it up — not rely on the request value being trustworthy.
        """
        response = self._post_add(price_pence=8000)

        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(cart[0]["price_pence"], 8000)

    def test_unknown_session_location_combo_returns_400(self):
        """No SessionPricing row for this combo → 400, nothing added to cart."""
        other_location = Location.objects.create(
            name="Pool B",
            slug="pool-b",
            address="2 Test Lane, London",
            is_active=True,
        )
        response = self._post_add(
            price_pence=8000,
            location_id=other_location.pk,
        )

        self.assertEqual(response.status_code, 400)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 0)

    def test_unknown_session_type_returns_400(self):
        """Non-existent session_type_id → 400."""
        response = self._post_add(price_pence=8000, session_type_id=99999)

        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Fix 3: Atomic stock deduction
# ---------------------------------------------------------------------------

class StockDeductionTest(TestCase):
    """
    confirm_order must use F('stock') - quantity in a single DB UPDATE
    rather than read-modify-write.  This test suite covers:
      - stock decrements correctly on payment
      - stock never goes below zero (stock__gte guard)
      - same Stripe event processed twice deducts stock only once
    """

    def _make_order(self, stock: int, quantity: int, event_id: str = "evt_test_001"):
        category = ProductCategory.objects.create(
            name="Caps", slug=f"caps-{event_id}"
        )
        product = Product.objects.create(
            name="Silicone Cap",
            slug=f"cap-{event_id}",
            category=category,
            price_pence=2400,
            stock=stock,
            is_active=True,
        )
        order = Order.objects.create(
            client_name="Test Client",
            client_email="test@example.com",
            subtotal_pence=2400 * quantity,
            total_pence=2400 * quantity,
        )
        OrderItem.objects.create(
            order=order,
            item_type=OrderItem.ITEM_TYPE_PRODUCT,
            product=product,
            quantity=quantity,
            price_pence=2400,
            label="Silicone Cap",
        )
        event = PaymentEvent(
            order_reference=str(order.reference),
            amount_pence=2400 * quantity,
            currency="GBP",
            provider_event_id=event_id,
            payment_intent_id=f"pi_{event_id}",
            raw_payload={},
        )
        return product, order, event

    def test_stock_decremented_by_quantity(self):
        """Normal payment: stock goes from 5 to 3 when quantity=2."""
        product, _, event = self._make_order(stock=5, quantity=2)

        confirm_order(event)

        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

    def test_stock_decremented_to_zero(self):
        """Buying the last item brings stock to exactly 0."""
        product, _, event = self._make_order(stock=1, quantity=1)

        confirm_order(event)

        product.refresh_from_db()
        self.assertEqual(product.stock, 0)

    def test_stock_does_not_go_negative(self):
        """
        If stock < quantity at deduction time, the UPDATE is skipped.
        The order is still confirmed; we just don't deduct what isn't there.
        This is the stock__gte guard on the F() UPDATE.
        """
        product, _, event = self._make_order(stock=1, quantity=2, event_id="evt_understock")

        confirm_order(event)

        product.refresh_from_db()
        self.assertEqual(product.stock, 1)  # unchanged — guard fired

    def test_stock_deduction_is_idempotent(self):
        """
        The same Stripe event ID processed twice must only deduct stock once.
        The PaymentRecord unique constraint on stripe_event_id handles this.
        """
        product, _, event = self._make_order(stock=5, quantity=2, event_id="evt_idempotent")

        confirm_order(event)
        result = confirm_order(event)  # duplicate — should be a no-op

        self.assertIsNone(result, "Duplicate event should return None")
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)  # 5 - 2, not 5 - 4

    def test_order_status_set_to_paid(self):
        """Sanity check: the order itself is marked paid after confirmation."""
        _, order, event = self._make_order(stock=5, quantity=1, event_id="evt_statuspaid")

        confirm_order(event)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)

    def test_payment_record_created(self):
        """A PaymentRecord audit row is created for every processed event."""
        from apps.payments.models import PaymentRecord

        _, _, event = self._make_order(stock=5, quantity=1, event_id="evt_auditrow")

        confirm_order(event)

        self.assertTrue(
            PaymentRecord.objects.filter(stripe_event_id="evt_auditrow").exists()
        )


# ---------------------------------------------------------------------------
# Fix 10 — dead widthratio tag removed from cart_drawer.html
# ---------------------------------------------------------------------------

class CartDrawerTemplateTest(TestCase):
    """
    Fix 10 — cart_drawer.html had a widthratio tag that computed a value it
    never used (line_total was referenced nowhere).  The tag is dead code and
    was also computing the wrong thing.  It must be removed.
    """

    def test_widthratio_tag_removed_from_template(self):
        import os
        from django.conf import settings as django_settings

        template_path = os.path.join(
            django_settings.BASE_DIR,
            "templates", "payments", "partials", "cart_drawer.html",
        )
        with open(template_path) as f:
            content = f.read()

        self.assertNotIn(
            "widthratio",
            content,
            "The dead {% widthratio %} tag must not appear in cart_drawer.html",
        )

    def test_line_total_variable_not_referenced(self):
        """The line_total variable that widthratio was (wrongly) producing is gone."""
        import os
        from django.conf import settings as django_settings

        template_path = os.path.join(
            django_settings.BASE_DIR,
            "templates", "payments", "partials", "cart_drawer.html",
        )
        with open(template_path) as f:
            content = f.read()

        self.assertNotIn(
            "line_total",
            content,
            "line_total was only produced by the dead widthratio tag and must be gone too",
        )


# ---------------------------------------------------------------------------
# Fix 3 — cart_add_product must look up price server-side
# ---------------------------------------------------------------------------

class CartAddProductPriceSecurityTest(TestCase):
    """
    cart_add_product must look up product.price_pence from the DB, never trust
    the client-supplied price_pence value.

    A client sending price_pence=1 for a £24 product must store 2400 in cart.
    """

    def setUp(self):
        from apps.shop.models import ProductCategory, Product
        cat = ProductCategory.objects.create(name="Caps", slug="caps")
        self.product = Product.objects.create(
            name="Silicone Cap",
            slug="silicone-cap",
            category=cat,
            price_pence=2400,  # £24 — canonical price
            stock=10,
            is_active=True,
        )

    def _post_add(self, price_pence):
        import json
        return self.client.post(
            "/cart/add-product/",
            data=json.dumps({
                "product_id": self.product.pk,
                "name": "Silicone Cap",
                "price_pence": price_pence,
                "qty": 1,
            }),
            content_type="application/json",
        )

    def test_tampered_low_price_is_ignored(self):
        """Sending price_pence=1 stores the DB price (2400), not 1."""
        response = self._post_add(price_pence=1)

        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["price_pence"], 2400)

    def test_tampered_zero_price_is_ignored(self):
        """Sending price_pence=0 stores the DB price."""
        response = self._post_add(price_pence=0)

        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(cart[0]["price_pence"], 2400)

    def test_inactive_product_returns_400(self):
        """Inactive products must not be addable to the cart."""
        import json
        from apps.shop.models import Product, ProductCategory

        cat = ProductCategory.objects.create(name="Goggles", slug="goggles")
        inactive = Product.objects.create(
            name="Old Goggles",
            slug="old-goggles",
            category=cat,
            price_pence=5000,
            stock=5,
            is_active=False,
        )

        response = self.client.post(
            "/cart/add-product/",
            data=json.dumps({"product_id": inactive.pk, "price_pence": 1, "qty": 1}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        cart = self.client.session.get("reachswim_cart", [])
        self.assertEqual(len(cart), 0)

    def test_nonexistent_product_returns_400(self):
        """Non-existent product_id must return 400."""
        import json
        response = self.client.post(
            "/cart/add-product/",
            data=json.dumps({"product_id": 99999, "price_pence": 1, "qty": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Fix 2 — cancel pending order releases pending bookings
# ---------------------------------------------------------------------------

class CancelPendingOrderTest(TestCase):
    """
    cancel_pending_order() must:
    - Cancel any pending Bookings linked to the Order
    - Mark the Order as expired
    - Be idempotent (second call on an already-expired order is a no-op)
    """

    def _make_pending_order_with_booking(self):
        """Create a pending Order linked to a pending Booking."""
        from apps.booking.models import (
            Booking, Location, SessionPricing, SessionType,
            RecurringSchedule,
        )
        import datetime

        session_type = SessionType.objects.create(
            name="Private", slug="priv-cancel", duration_minutes=60, is_active=True,
        )
        location = Location.objects.create(
            name="Pool C", slug="pool-c", address="3 Test Ln", is_active=True,
        )
        SessionPricing.objects.create(
            session_type=session_type, location=location, price_pence=8000,
        )
        booking = Booking.objects.create(
            session_type=session_type,
            location=location,
            date=datetime.date(2030, 6, 1),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(11, 0),
            client_name="Cancel Test",
            client_email="cancel@example.com",
            status=Booking.STATUS_PENDING,
            amount_pence=8000,
        )
        order = Order.objects.create(
            client_name="Cancel Test",
            client_email="cancel@example.com",
            subtotal_pence=8000,
            total_pence=8000,
        )
        OrderItem.objects.create(
            order=order,
            item_type=OrderItem.ITEM_TYPE_BOOKING,
            booking=booking,
            price_pence=8000,
            label="Private",
            quantity=1,
        )
        return order, booking

    def test_cancels_pending_booking_and_expires_order(self):
        from apps.payments.services.checkout import cancel_pending_order

        order, booking = self._make_pending_order_with_booking()

        cancel_pending_order(str(order.reference))

        order.refresh_from_db()
        booking.refresh_from_db()

        self.assertEqual(order.status, Order.STATUS_EXPIRED)
        from apps.booking.models import Booking
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_is_idempotent_on_expired_order(self):
        """Calling cancel_pending_order twice is safe — second call is a no-op."""
        from apps.payments.services.checkout import cancel_pending_order

        order, booking = self._make_pending_order_with_booking()

        cancel_pending_order(str(order.reference))
        cancel_pending_order(str(order.reference))  # no-op

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_EXPIRED)

    def test_does_not_cancel_paid_order(self):
        """A paid order must not be touched by cancel_pending_order."""
        from apps.payments.services.checkout import cancel_pending_order

        order, _ = self._make_pending_order_with_booking()
        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

        cancel_pending_order(str(order.reference))  # should be a no-op

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)

    def test_payment_cancel_view_calls_cancel(self):
        """
        The payment_cancel view must pop pending_order_ref from the session
        and cancel the order.
        """
        order, booking = self._make_pending_order_with_booking()

        session = self.client.session
        session["pending_order_ref"] = str(order.reference)
        session.save()

        response = self.client.get("/payments/cancel/")

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_EXPIRED)

        # Session key must be cleared
        self.assertNotIn("pending_order_ref", self.client.session)


# ---------------------------------------------------------------------------
# Fix 6 — Voucher.redeem() is atomic (F() expression)
# ---------------------------------------------------------------------------

class VoucherRedeemAtomicTest(TestCase):
    """
    Voucher.redeem() must use an F() expression to increment times_used
    atomically.  We can't simulate two true concurrent DB transactions in
    TestCase, but we can verify the core behaviour:
      - times_used increments correctly
      - the in-memory instance is refreshed from DB after the UPDATE
    """

    def _make_voucher(self, times_used=0, max_uses=5):
        import datetime
        from apps.payments.models import Voucher
        from django.utils import timezone
        return Voucher.objects.create(
            code="TESTCODE10",
            discount_type=Voucher.DISCOUNT_PERCENTAGE,
            discount_value=10,
            max_uses=max_uses,
            times_used=times_used,
            valid_from=timezone.now() - datetime.timedelta(days=1),
            is_active=True,
        )

    def test_redeem_increments_times_used(self):
        from apps.payments.models import Voucher
        v = self._make_voucher(times_used=0)

        v.redeem()

        v.refresh_from_db()
        self.assertEqual(v.times_used, 1)

    def test_redeem_refreshes_in_memory_instance(self):
        """After redeem(), the in-memory times_used must reflect the DB value."""
        v = self._make_voucher(times_used=3)

        v.redeem()

        # No additional refresh_from_db call — redeem() must do it
        self.assertEqual(v.times_used, 4)

    def test_multiple_redeems_accumulate(self):
        """Calling redeem() three times brings times_used from 0 to 3."""
        v = self._make_voucher(times_used=0)

        v.redeem()
        v.redeem()
        v.redeem()

        v.refresh_from_db()
        self.assertEqual(v.times_used, 3)

    def test_voucher_marked_exhausted_after_max_uses(self):
        """
        is_valid() must return False once times_used >= max_uses,
        proving redeem() + is_valid() interact correctly.
        """
        from django.utils import timezone
        v = self._make_voucher(times_used=4, max_uses=5)

        v.redeem()  # brings times_used to 5

        v.refresh_from_db()
        self.assertFalse(
            v.is_valid(subtotal_pence=10000),
            "Voucher should be invalid once times_used reaches max_uses",
        )
