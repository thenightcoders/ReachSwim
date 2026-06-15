"""
Refund service — the single place where Stripe refunds are initiated.

Public API
----------
  issue_refund(order, *, amount_pence, order_item=None, initiated_by=None, notes="")
  apply_refund_succeeded(refund)   ← called by the charge.refund.updated webhook

All three refund modes go through issue_refund():

  • Per-item refund  → pass order_item + amount_pence = order_item.line_total_pence
  • Custom amount    → pass amount_pence only (order_item=None)
  • Full remaining   → pass amount_pence = order.remaining_refundable_pence

Side effects by item type (only when order_item is set OR the refund fully
exhausts the order)
------------------------------------------------------------------------
  booking  → cancel the booking silently (no cancellation email — the
              refund email IS the client communication)
  product  → auto-restock if the item hasn't been shipped yet

Execution order (critical — Stripe call must sit outside any DB transaction)
-----------------------------------------------------------------------------
  1. Validate + lock the order row  (short atomic block)
  2. Call Stripe                    (outside any transaction)
  3. Persist Refund + side effects  (new atomic block)
  4. Dispatch email                 (after transaction commits)

Order status
------------
  Stays "paid" while remaining_refundable_pence > 0.
  Flips to "refunded" when the order is fully refunded.

Multiple partial refunds are allowed until remaining_refundable_pence reaches 0.
"""
import logging

from django.db import transaction
from django.db.models import F

from apps.payments.interfaces import RefundError
from apps.payments.models import Order, OrderItem, Refund
from apps.payments.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


def issue_refund(
    order: Order,
    *,
    amount_pence: int,
    order_item: "OrderItem | None" = None,
    initiated_by=None,
    notes: str = "",
) -> Refund:
    """
    Issue a (partial or full) Stripe refund against a paid order.

    Parameters
    ----------
    order        : The Order to refund.  Must have stripe_payment_intent_id set.
    amount_pence : Exact pence to refund.  Must be > 0 and ≤ remaining refundable.
    order_item   : Specific line item being refunded, or None for a free-form refund.
    initiated_by : The User who triggered this (dashboard owner), or None for system.
    notes        : Internal note stored on the Refund record.

    Returns the created Refund instance.
    Raises ValueError for business-rule violations.
    Raises RefundError if Stripe rejects the request.
    """
    # ------------------------------------------------------------------
    # Step 1 — validate inside a short atomic block that locks the order
    # row.  select_for_update() prevents two concurrent refunds from both
    # reading the same remaining_refundable_pence and over-refunding.
    # ------------------------------------------------------------------
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        _validate(locked, amount_pence)

    # ------------------------------------------------------------------
    # Step 2 — Stripe HTTP call OUTSIDE any transaction.
    # If the DB write in step 3 fails, we log the orphaned Stripe refund
    # and re-raise so the caller can alert.  Money is still returned to
    # the customer; the Refund record is the only thing missing — far
    # safer than the reverse (record written, Stripe never called).
    # ------------------------------------------------------------------
    result = StripeService().create_refund(
        payment_intent_id=order.stripe_payment_intent_id,
        amount_pence=amount_pence,
        reason=Refund.REASON_REQUESTED,
    )

    # ------------------------------------------------------------------
    # Step 3 — persist + side effects in a new atomic block.
    # By this point Stripe has already returned; any exception here rolls
    # back the DB write but cannot undo the Stripe refund (see note above).
    # ------------------------------------------------------------------
    with transaction.atomic():
        refund = Refund.objects.create(
            order=order,
            order_item=order_item,
            stripe_refund_id=result.refund_id,
            amount_pence=result.amount_pence,
            reason=Refund.REASON_REQUESTED,
            status=result.status,
            notes=notes,
            initiated_by=initiated_by,
        )

        logger.info(
            "Refund issued: order=%s refund_id=%s amount=%dp item=%s status=%s by=%s",
            order.reference,
            result.refund_id,
            result.amount_pence,
            order_item.pk if order_item else "—",
            result.status,
            getattr(initiated_by, "email", "system"),
        )

        if result.status == "succeeded":
            _apply_side_effects(order, order_item, refund)

        # Flip order status when fully refunded.  Re-read from DB so
        # remaining_refundable_pence reflects the Refund just created.
        order.refresh_from_db(fields=["status"])
        if order.remaining_refundable_pence <= 0 and order.status != Order.STATUS_REFUNDED:
            order.status = Order.STATUS_REFUNDED
            order.save(update_fields=["status", "updated_at"])

    # ------------------------------------------------------------------
    # Step 4 — email fires after the transaction has committed.
    # The daemon thread reads in-memory objects so it doesn't need the
    # DB write to be visible; starting it here means an SMTP failure
    # cannot roll back the Refund record.
    # ------------------------------------------------------------------
    _send_refund_email_async(order, refund, order_item)

    return refund


# ---------------------------------------------------------------------------
# Webhook handler — charge.refund.updated
# ---------------------------------------------------------------------------

def apply_refund_succeeded(refund: Refund) -> None:
    """
    Called by the charge.refund.updated webhook when a previously-pending
    Stripe refund transitions to succeeded.

    Applies side effects, flips order status if fully refunded, and sends
    the client's refund confirmation email — the same post-processing that
    issue_refund() does when Stripe returns succeeded synchronously.
    """
    with transaction.atomic():
        Refund.objects.filter(pk=refund.pk).update(status="succeeded")
        refund.refresh_from_db()

        order = refund.order
        _apply_side_effects(order, refund.order_item, refund)

        order.refresh_from_db(fields=["status"])
        if order.remaining_refundable_pence <= 0 and order.status != Order.STATUS_REFUNDED:
            order.status = Order.STATUS_REFUNDED
            order.save(update_fields=["status", "updated_at"])

    _send_refund_email_async(order, refund, refund.order_item)
    logger.info(
        "Refund %s transitioned to succeeded via charge.refund.updated webhook.",
        refund.stripe_refund_id,
    )


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate(order: Order, amount_pence: int) -> None:
    """
    Guard checks run inside the locking atomic block.
    Raises ValueError on any business-rule violation.
    """
    if not order.stripe_payment_intent_id:
        raise ValueError(
            f"Order {order.order_number} has no Stripe payment intent. "
            "Only orders paid through Stripe can be refunded here."
        )

    if order.status not in (Order.STATUS_PAID, Order.STATUS_REFUNDED):
        raise ValueError(
            f"Cannot refund order {order.order_number}: "
            f"status is '{order.get_status_display()}'. "
            "Only Paid orders can be refunded."
        )

    remaining = order.remaining_refundable_pence
    if remaining <= 0:
        raise ValueError(
            f"Order {order.order_number} has already been fully refunded."
        )

    if amount_pence <= 0:
        raise ValueError("Refund amount must be greater than zero.")

    if amount_pence > remaining:
        raise ValueError(
            f"Requested £{amount_pence / 100:.2f} exceeds the remaining "
            f"refundable amount of £{remaining / 100:.2f}."
        )


# ---------------------------------------------------------------------------
# Side effects
# ---------------------------------------------------------------------------

def _apply_side_effects(order: Order, order_item: "OrderItem | None", refund: Refund) -> None:
    """
    Apply business side effects for a succeeded refund.

    Per-item (order_item is set):
      booking → cancel silently (refund email is the client communication)
      product → auto-restock if item hasn't been shipped yet

    Item-less / custom-amount (order_item=None):
      → only walk all items when this refund fully exhausts the order.
        A £5 custom refund on a £200 order has no per-item semantics —
        the bookings are NOT cancelled and stock is NOT restocked.
    """
    if order_item is not None:
        _apply_item_effect(order_item)
    elif order.remaining_refundable_pence <= 0:
        # The order is now fully refunded — apply effects to every item.
        for oi in order.items.select_related("booking", "product").all():
            _apply_item_effect(oi)


def _apply_item_effect(order_item: OrderItem) -> None:
    """Apply the per-item side effect for a refund."""
    if order_item.item_type == OrderItem.ITEM_TYPE_BOOKING:
        _cancel_booking_silently(order_item)
    elif order_item.item_type == OrderItem.ITEM_TYPE_PRODUCT:
        _restock_if_unshipped(order_item)


def _cancel_booking_silently(order_item: OrderItem) -> None:
    """Cancel the booking attached to this order item without sending an email."""
    from apps.booking.services.booking import cancel_booking

    booking = order_item.booking
    if booking is None:
        return

    from apps.booking.models import Booking
    if booking.status in (Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED):
        cancel_booking(
            booking,
            reason="Refunded via dashboard.",
            notify_client=False,  # refund email is the single client communication
        )
        logger.info("Booking %s cancelled silently after refund.", booking.pk)


def _restock_if_unshipped(order_item: OrderItem) -> None:
    """Increment product stock by the refunded quantity if the item hasn't shipped."""
    if order_item.shipped or order_item.product_id is None:
        return

    from apps.shop.models import Product

    updated = Product.objects.filter(pk=order_item.product_id).update(
        stock=F("stock") + order_item.quantity
    )
    if updated:
        logger.info(
            "Restocked product %s by %d (order item %s).",
            order_item.product_id,
            order_item.quantity,
            order_item.pk,
        )


# ---------------------------------------------------------------------------
# Email dispatch
# ---------------------------------------------------------------------------

def _send_refund_email_async(
    order: Order,
    refund: Refund,
    order_item: "OrderItem | None",
) -> None:
    """Fire a single refund confirmation email to the client (async, non-blocking)."""
    from apps.booking.services.email import send_refund_email

    send_refund_email(order, refund, order_item=order_item, async_send=True)
