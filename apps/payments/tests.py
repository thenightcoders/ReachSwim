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


# =============================================================================
# Refund service — validation, happy paths, race detection
# =============================================================================

class RefundServiceValidationTest(TestCase):
    """
    _validate() must reject all bad inputs before Stripe is ever called.
    All checks happen inside a locking atomic block in issue_refund() step 1.
    """

    def setUp(self):
        self.order = Order.objects.create(
            client_name="Test Client",
            client_email="test@example.com",
            subtotal_pence=8000,
            total_pence=8000,
            stripe_payment_intent_id="pi_test_123",
            status=Order.STATUS_PAID,
        )

    def _issue(self, **kwargs):
        """Call issue_refund with Stripe mocked to avoid HTTP."""
        from unittest.mock import patch
        from apps.payments.interfaces import RefundResult
        from apps.payments.services.refund import issue_refund

        dummy = RefundResult(refund_id="re_test", amount_pence=kwargs.get("amount_pence", 1000), status="succeeded")
        with patch("apps.payments.services.refund.StripeService.create_refund", return_value=dummy):
            with patch("apps.payments.services.refund._send_refund_email_async"):
                return issue_refund(self.order, **kwargs)

    def test_no_stripe_pi_raises(self):
        self.order.stripe_payment_intent_id = ""
        self.order.save(update_fields=["stripe_payment_intent_id"])
        with self.assertRaises(ValueError, msg="Should raise for missing PI"):
            self._issue(amount_pence=1000)

    def test_pending_order_raises(self):
        self.order.status = Order.STATUS_PENDING
        self.order.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            self._issue(amount_pence=1000)

    def test_expired_order_raises(self):
        self.order.status = Order.STATUS_EXPIRED
        self.order.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            self._issue(amount_pence=1000)

    def test_zero_amount_raises(self):
        with self.assertRaises(ValueError, msg="amount_pence=0 must be rejected"):
            self._issue(amount_pence=0)

    def test_negative_amount_raises(self):
        with self.assertRaises(ValueError):
            self._issue(amount_pence=-100)

    def test_over_remaining_raises(self):
        with self.assertRaises(ValueError, msg="8001p > 8000p remaining"):
            self._issue(amount_pence=8001)

    def test_already_fully_refunded_raises(self):
        from apps.payments.models import Refund
        Refund.objects.create(
            order=self.order,
            stripe_refund_id="re_prev",
            amount_pence=8000,
            reason=Refund.REASON_REQUESTED,
            status="succeeded",
        )
        with self.assertRaises(ValueError, msg="Nothing left to refund"):
            self._issue(amount_pence=1000)


class RefundServiceIssueRefundTest(TestCase):
    """
    issue_refund() happy paths: Refund record creation, order status flip,
    side effects, and the re-lock race detection in step 3.
    """

    def setUp(self):
        from apps.booking.models import Location, SessionType
        self.order = Order.objects.create(
            client_name="Test Client",
            client_email="test@example.com",
            subtotal_pence=8000,
            total_pence=8000,
            stripe_payment_intent_id="pi_test_abc",
            status=Order.STATUS_PAID,
        )
        self.session_type = SessionType.objects.create(
            name="Private", slug="priv-refund-test", duration_minutes=60, is_active=True,
        )
        self.location = Location.objects.create(
            name="Pool R", slug="pool-r", address="R Lane", is_active=True,
        )

    def _mock_stripe(self, amount_pence, status="succeeded", refund_id="re_stripe001"):
        from unittest.mock import patch
        from apps.payments.interfaces import RefundResult
        return RefundResult(refund_id=refund_id, amount_pence=amount_pence, status=status)

    def _issue(self, amount_pence, order_item=None, stripe_result=None):
        from unittest.mock import patch
        from apps.payments.services.refund import issue_refund

        result = stripe_result or self._mock_stripe(amount_pence)
        with patch("apps.payments.services.refund.StripeService.create_refund", return_value=result):
            with patch("apps.payments.services.refund._send_refund_email_async"):
                return issue_refund(
                    self.order,
                    amount_pence=amount_pence,
                    order_item=order_item,
                )

    def test_refund_record_created(self):
        from apps.payments.models import Refund

        self._issue(amount_pence=3000)

        self.assertEqual(Refund.objects.filter(order=self.order).count(), 1)
        refund = Refund.objects.get(order=self.order)
        self.assertEqual(refund.amount_pence, 3000)
        self.assertEqual(refund.stripe_refund_id, "re_stripe001")
        self.assertEqual(refund.status, "succeeded")

    def test_partial_refund_leaves_order_paid(self):
        """A partial refund must NOT flip the order to refunded."""
        self._issue(amount_pence=3000)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)

    def test_full_refund_flips_order_to_refunded(self):
        """Refunding the full remaining balance must flip status to refunded."""
        self._issue(amount_pence=8000)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    def test_two_partial_refunds_flip_to_refunded_on_second(self):
        """Draining remaining across two calls flips on the second call."""
        self._issue(amount_pence=5000, stripe_result=self._mock_stripe(5000, refund_id="re_1"))
        self._issue(amount_pence=3000, stripe_result=self._mock_stripe(3000, refund_id="re_2"))

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    def test_pending_stripe_refund_does_not_flip_order(self):
        """A pending Stripe refund must not apply side effects or flip status."""
        self._issue(amount_pence=8000, stripe_result=self._mock_stripe(8000, status="pending"))

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID,
                         "Pending refund must not flip order to refunded")

    def test_race_condition_raises_refund_error(self):
        """
        Step 3 re-acquires the lock and re-checks remaining.
        If a concurrent refund drained the balance between step 1 and step 3,
        issue_refund() must raise RefundError rather than over-refunding.
        """
        from unittest.mock import patch
        from apps.payments.interfaces import RefundError, RefundResult
        from apps.payments.models import Refund
        from apps.payments.services.refund import issue_refund

        def drain_then_return(*args, **kwargs):
            # Simulate a concurrent refund winning the race while Stripe was
            # processing: drain the entire order balance before step 3 runs.
            Refund.objects.create(
                order=self.order,
                stripe_refund_id="re_concurrent",
                amount_pence=8000,
                reason=Refund.REASON_REQUESTED,
                status="succeeded",
            )
            return RefundResult(refund_id="re_loser", amount_pence=8000, status="succeeded")

        with patch("apps.payments.services.refund.StripeService.create_refund", side_effect=drain_then_return):
            with patch("apps.payments.services.refund._send_refund_email_async"):
                with self.assertRaises(RefundError):
                    issue_refund(self.order, amount_pence=8000)

    def test_item_booking_side_effect_cancels_booking(self):
        """
        A per-item refund against a booking item must cancel the booking silently.
        """
        import datetime
        from unittest.mock import patch
        from apps.booking.models import Booking

        booking = Booking.objects.create(
            session_type=self.session_type,
            location=self.location,
            date=datetime.date(2030, 7, 1),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            client_name="Test",
            client_email="t@t.com",
            status=Booking.STATUS_CONFIRMED,
            amount_pence=8000,
        )
        order_item = OrderItem.objects.create(
            order=self.order,
            item_type=OrderItem.ITEM_TYPE_BOOKING,
            booking=booking,
            price_pence=8000,
            label="Private",
        )

        with patch("apps.payments.services.refund.StripeService.create_refund",
                   return_value=self._mock_stripe(8000)):
            with patch("apps.payments.services.refund._send_refund_email_async"):
                from apps.payments.services.refund import issue_refund
                issue_refund(self.order, amount_pence=8000, order_item=order_item)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)

    def test_custom_amount_partial_does_not_cancel_booking(self):
        """
        A custom-amount partial refund with no order_item must NOT cancel bookings
        — only full remaining refunds with no order_item trigger side effects.
        """
        import datetime
        from apps.booking.models import Booking

        booking = Booking.objects.create(
            session_type=self.session_type,
            location=self.location,
            date=datetime.date(2030, 8, 1),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            client_name="Test",
            client_email="t@t.com",
            status=Booking.STATUS_CONFIRMED,
            amount_pence=8000,
        )
        OrderItem.objects.create(
            order=self.order,
            item_type=OrderItem.ITEM_TYPE_BOOKING,
            booking=booking,
            price_pence=8000,
            label="Private",
        )

        # Partial custom refund — no order_item, doesn't exhaust remaining.
        self._issue(amount_pence=2000, stripe_result=self._mock_stripe(2000, refund_id="re_partial"))

        booking.refresh_from_db()
        self.assertEqual(
            booking.status, Booking.STATUS_CONFIRMED,
            "Partial custom refund must not cancel the booking",
        )


class RefundServiceApplySucceededTest(TestCase):
    """
    apply_refund_succeeded() is called by the charge.refund.updated webhook
    when a previously-pending Stripe refund transitions to succeeded.
    """

    def setUp(self):
        self.order = Order.objects.create(
            client_name="Test",
            client_email="t@t.com",
            subtotal_pence=5000,
            total_pence=5000,
            stripe_payment_intent_id="pi_webhook_test",
            status=Order.STATUS_PAID,
        )
        from apps.payments.models import Refund
        self.refund = Refund.objects.create(
            order=self.order,
            stripe_refund_id="re_pending_001",
            amount_pence=5000,
            reason=Refund.REASON_REQUESTED,
            status="pending",
        )

    def test_refund_status_flipped_to_succeeded(self):
        from apps.payments.models import Refund
        from apps.payments.services.refund import apply_refund_succeeded
        from unittest.mock import patch

        with patch("apps.payments.services.refund._send_refund_email_async"):
            apply_refund_succeeded(self.refund)

        self.refund.refresh_from_db()
        self.assertEqual(self.refund.status, "succeeded")

    def test_full_refund_flips_order_status(self):
        from apps.payments.services.refund import apply_refund_succeeded
        from unittest.mock import patch

        with patch("apps.payments.services.refund._send_refund_email_async"):
            apply_refund_succeeded(self.refund)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    def test_partial_pending_refund_does_not_flip_order(self):
        """A partial pending→succeeded refund must not flip order if balance remains."""
        from apps.payments.models import Refund
        from apps.payments.services.refund import apply_refund_succeeded
        from unittest.mock import patch

        partial = Refund.objects.create(
            order=self.order,
            stripe_refund_id="re_partial_pending",
            amount_pence=2000,   # partial — 3000 still remains
            reason=Refund.REASON_REQUESTED,
            status="pending",
        )

        with patch("apps.payments.services.refund._send_refund_email_async"):
            apply_refund_succeeded(partial)

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status, Order.STATUS_PAID,
            "Partial refund must not flip order to refunded",
        )

    def test_is_idempotent(self):
        """
        apply_refund_succeeded() called twice must not raise or double-apply.
        The webhook handler's status check prevents a second call, but the
        service itself must be safe to call twice.
        """
        from apps.payments.services.refund import apply_refund_succeeded
        from unittest.mock import patch

        with patch("apps.payments.services.refund._send_refund_email_async"):
            apply_refund_succeeded(self.refund)
            apply_refund_succeeded(self.refund)  # no-op: status already succeeded

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)


# =============================================================================
# Payment reminder service — link building and email dispatch
# =============================================================================

class PaymentReminderMakePaymentLinkTest(TestCase):
    """make_payment_link() builds a signed URL or returns "" gracefully."""

    def setUp(self):
        import datetime
        from apps.booking.models import Booking, Location, SessionType
        self.session_type = SessionType.objects.create(
            name="Private", slug="priv-reminder", duration_minutes=60, is_active=True,
        )
        self.location = Location.objects.create(
            name="Pool P", slug="pool-p", address="P Lane", is_active=True,
        )
        self.booking = Booking.objects.create(
            session_type=self.session_type,
            location=self.location,
            date=datetime.date(2030, 9, 1),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(11, 0),
            client_name="Reminder Test",
            client_email="reminder@test.com",
            status="pending",
            amount_pence=8000,
        )
        self.order = Order.objects.create(
            client_name="Reminder Test",
            client_email="reminder@test.com",
            subtotal_pence=8000,
            total_pence=8000,
            stripe_payment_intent_id="pi_reminder",
            status=Order.STATUS_PENDING,
        )
        OrderItem.objects.create(
            order=self.order,
            item_type=OrderItem.ITEM_TYPE_BOOKING,
            booking=self.booking,
            price_pence=8000,
            label="Private",
        )

    def test_returns_empty_string_for_booking_with_no_order_item(self):
        import datetime
        from apps.booking.models import Booking
        from apps.payments.services.reminder import make_payment_link

        orphan = Booking.objects.create(
            session_type=self.session_type,
            location=self.location,
            date=datetime.date(2030, 9, 2),
            start_time=datetime.time(10, 0),
            client_name="Orphan",
            client_email="orphan@test.com",
            status="pending",
            amount_pence=8000,
        )

        link = make_payment_link(orphan)
        self.assertEqual(link, "")

    def test_returns_signed_url_containing_pay_resume(self):
        from apps.payments.services.reminder import make_payment_link

        link = make_payment_link(self.booking)

        self.assertIn("/pay/resume/", link)
        self.assertTrue(link.startswith("http") or link.startswith("/pay/"))

    def test_signed_url_decodes_to_correct_order_reference(self):
        from django.core import signing
        from apps.payments.services.reminder import make_payment_link, REMINDER_LINK_MAX_AGE

        link = make_payment_link(self.booking)

        # Extract token from URL: /pay/resume/<token>/
        token = link.rstrip("/").split("/")[-1]
        decoded = signing.loads(token, salt="payment-reminder", max_age=REMINDER_LINK_MAX_AGE)
        self.assertEqual(decoded, str(self.order.reference))


class PaymentReminderSendEmailTest(TestCase):
    """send_payment_reminder_email() sync/async paths and PaymentReminder creation."""

    def setUp(self):
        import datetime
        from apps.booking.models import Booking, Location, SessionType

        session_type = SessionType.objects.create(
            name="Group", slug="group-reminder", duration_minutes=45, is_active=True,
        )
        location = Location.objects.create(
            name="Pool G", slug="pool-g", address="G Lane", is_active=True,
        )
        self.booking = Booking.objects.create(
            session_type=session_type,
            location=location,
            date=datetime.date(2030, 10, 1),
            start_time=datetime.time(8, 0),
            end_time=datetime.time(9, 0),
            client_name="Group Client",
            client_email="group@test.com",
            status="pending",
            amount_pence=4500,
        )
        order = Order.objects.create(
            client_name="Group Client",
            client_email="group@test.com",
            subtotal_pence=4500,
            total_pence=4500,
            stripe_payment_intent_id="pi_group",
            status=Order.STATUS_PENDING,
        )
        OrderItem.objects.create(
            order=order,
            item_type=OrderItem.ITEM_TYPE_BOOKING,
            booking=self.booking,
            price_pence=4500,
            label="Group",
        )

    def test_sync_success_creates_payment_reminder(self):
        from unittest.mock import patch
        from apps.payments.models import PaymentReminder
        from apps.payments.services.reminder import send_payment_reminder_email

        with patch("apps.payments.services.reminder.send_payment_reminder", return_value=True):
            result = send_payment_reminder_email(
                self.booking,
                source=PaymentReminder.SOURCE_MANUAL,
                async_send=False,
            )

        self.assertIsNotNone(result)
        self.assertEqual(PaymentReminder.objects.filter(booking=self.booking).count(), 1)

    def test_sync_smtp_failure_creates_no_record(self):
        from unittest.mock import patch
        from apps.payments.models import PaymentReminder
        from apps.payments.services.reminder import send_payment_reminder_email

        with patch("apps.payments.services.reminder.send_payment_reminder", return_value=False):
            result = send_payment_reminder_email(
                self.booking,
                source=PaymentReminder.SOURCE_AUTO,
                async_send=False,
            )

        self.assertIsNone(result)
        self.assertEqual(
            PaymentReminder.objects.filter(booking=self.booking).count(), 0,
            "Failed SMTP must not write a PaymentReminder — constraint must stay unblocked for retry",
        )

    def test_async_path_writes_reminder_optimistically(self):
        from unittest.mock import patch
        from apps.payments.models import PaymentReminder
        from apps.payments.services.reminder import send_payment_reminder_email

        with patch("apps.payments.services.reminder.send_payment_reminder", return_value=None):
            result = send_payment_reminder_email(
                self.booking,
                source=PaymentReminder.SOURCE_MANUAL,
                async_send=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            PaymentReminder.objects.filter(booking=self.booking).count(), 1,
            "Async path must write PaymentReminder immediately (optimistic)",
        )

    def test_sync_rule_constraint_prevents_double_send(self):
        """
        The DB unique constraint on (booking, rule) prevents the same rule from
        sending twice even if the task runs twice.
        """
        from unittest.mock import patch
        from django.db import IntegrityError
        from apps.payments.models import PaymentReminder, PaymentReminderRule
        from apps.payments.services.reminder import send_payment_reminder_email

        rule = PaymentReminderRule.objects.create(delay_hours=24)

        with patch("apps.payments.services.reminder.send_payment_reminder", return_value=True):
            send_payment_reminder_email(
                self.booking,
                source=PaymentReminder.SOURCE_AUTO,
                rule=rule,
                async_send=False,
            )
            # Second send: the DB unique constraint should fire.
            with self.assertRaises(IntegrityError):
                send_payment_reminder_email(
                    self.booking,
                    source=PaymentReminder.SOURCE_AUTO,
                    rule=rule,
                    async_send=False,
                )


# =============================================================================
# Payment views — resume_payment and _handle_refund_update
# =============================================================================

class ResumePaymentViewTest(TestCase):
    """resume_payment() view: token validation, order status guards."""

    def _make_order(self, status=None):
        order = Order.objects.create(
            client_name="Resume Test",
            client_email="resume@test.com",
            subtotal_pence=8000,
            total_pence=8000,
            stripe_payment_intent_id="pi_resume",
            status=status or Order.STATUS_PENDING,
        )
        return order

    def _make_token(self, order):
        from django.core import signing
        return signing.dumps(str(order.reference), salt="payment-reminder")

    def test_valid_token_pending_order_redirects_to_stripe(self):
        from unittest.mock import patch
        from apps.payments.interfaces import PaymentSession

        order = self._make_order(status=Order.STATUS_PENDING)
        token = self._make_token(order)

        fake_session = PaymentSession(redirect_url="https://checkout.stripe.com/pay/cs_test", provider_session_id="cs_test")
        with patch("apps.payments.views.create_checkout_session", return_value=fake_session):
            response = self.client.get(f"/pay/resume/{token}/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("stripe.com", response["Location"])

    def test_expired_token_returns_410(self):
        from unittest.mock import patch
        from django.core import signing

        order = self._make_order()
        token = signing.dumps(str(order.reference), salt="payment-reminder")

        # Patch max_age to 0 so any token is considered expired.
        with patch("apps.payments.views.REMINDER_LINK_MAX_AGE", 0):
            import time; time.sleep(0.01)
            response = self.client.get(f"/pay/resume/{token}/")

        self.assertEqual(response.status_code, 410)

    def test_bad_signature_returns_410(self):
        response = self.client.get("/pay/resume/totally-invalid-token/")
        self.assertEqual(response.status_code, 410)

    def test_paid_order_renders_already_paid(self):
        order = self._make_order(status=Order.STATUS_PAID)
        token = self._make_token(order)

        response = self.client.get(f"/pay/resume/{token}/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "payments/already_paid.html")

    def test_cancelled_order_returns_410(self):
        order = self._make_order(status=Order.STATUS_EXPIRED)
        token = self._make_token(order)

        response = self.client.get(f"/pay/resume/{token}/")

        self.assertEqual(response.status_code, 410)

    def test_refunded_order_returns_410(self):
        order = self._make_order(status=Order.STATUS_REFUNDED)
        token = self._make_token(order)

        response = self.client.get(f"/pay/resume/{token}/")

        self.assertEqual(response.status_code, 410)


class HandleRefundUpdateWebhookTest(TestCase):
    """_handle_refund_update() routes charge.refund.updated events correctly."""

    def setUp(self):
        self.order = Order.objects.create(
            client_name="Webhook Test",
            client_email="wh@test.com",
            subtotal_pence=6000,
            total_pence=6000,
            stripe_payment_intent_id="pi_wh_001",
            status=Order.STATUS_PAID,
        )
        from apps.payments.models import Refund
        self.refund = Refund.objects.create(
            order=self.order,
            stripe_refund_id="re_wh_pending",
            amount_pence=6000,
            reason=Refund.REASON_REQUESTED,
            status="pending",
        )

    def _raw_event(self, stripe_refund_id, status):
        return {
            "type": "charge.refund.updated",
            "data": {
                "object": {
                    "id": stripe_refund_id,
                    "status": status,
                }
            },
        }

    def test_succeeded_calls_apply_refund_succeeded(self):
        from unittest.mock import patch
        from apps.payments.views import _handle_refund_update

        with patch("apps.payments.views.apply_refund_succeeded") as mock_apply:
            _handle_refund_update(self._raw_event("re_wh_pending", "succeeded"))

        mock_apply.assert_called_once()
        called_refund = mock_apply.call_args[0][0]
        self.assertEqual(called_refund.pk, self.refund.pk)

    def test_failed_updates_status_only(self):
        from apps.payments.models import Refund
        from apps.payments.views import _handle_refund_update

        _handle_refund_update(self._raw_event("re_wh_pending", "failed"))

        self.refund.refresh_from_db()
        self.assertEqual(self.refund.status, "failed")

    def test_unknown_stripe_refund_id_is_ignored(self):
        """Refund issued outside our dashboard — no local record — must be a no-op."""
        from apps.payments.views import _handle_refund_update

        # Should not raise — just log and return.
        _handle_refund_update(self._raw_event("re_unknown_xyz", "succeeded"))

    def test_already_at_new_status_is_no_op(self):
        """
        If refund.status == new_status, the webhook handler returns early.
        apply_refund_succeeded must NOT be called.
        """
        from unittest.mock import patch
        from apps.payments.models import Refund
        from apps.payments.views import _handle_refund_update

        # Bring the refund to succeeded first.
        Refund.objects.filter(pk=self.refund.pk).update(status="succeeded")

        with patch("apps.payments.views.apply_refund_succeeded") as mock_apply:
            _handle_refund_update(self._raw_event("re_wh_pending", "succeeded"))

        mock_apply.assert_not_called()

    def test_malformed_payload_does_not_raise(self):
        """Unexpected payload shapes must be handled gracefully (log + return)."""
        from apps.payments.views import _handle_refund_update

        bad_payloads = [
            {},
            {"data": {}},
            {"data": {"object": None}},
            {"data": {"object": {"id": None, "status": "succeeded"}}},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                _handle_refund_update(payload)  # must not raise
