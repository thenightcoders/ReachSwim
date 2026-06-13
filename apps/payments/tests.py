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
