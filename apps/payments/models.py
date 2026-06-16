"""
Payment models.

Order + OrderItem group one or more bookings into a single checkout.
PaymentRecord logs every Stripe event for audit.
Voucher handles discount codes.
PackagePurchase tracks multi-session bundles.
PaymentReminderRule + PaymentReminder handle pending-payment email nudges.
"""
import uuid

from django.db import models
from django.utils import timezone


# =============================================================================
# Order  (groups bookings into a single checkout)
# =============================================================================

class Order(models.Model):
    """
    A checkout session — one Order can contain multiple bookings.
    Created as 'pending' before Stripe redirect, flipped to 'paid' on
    webhook confirmation.
    """

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_REFUNDED = "refunded"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending payment"),
        (STATUS_PAID, "Paid"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_EXPIRED, "Expired"),
    ]

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Client info (denormalised — order persists even if bookings are cancelled)
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=30, blank=True)

    # Money
    subtotal_pence = models.PositiveIntegerField(default=0)
    discount_pence = models.PositiveIntegerField(default=0)
    total_pence = models.PositiveIntegerField(default=0)
    voucher_code = models.CharField(max_length=30, blank=True)

    # Status + Stripe
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.reference} — {self.get_status_display()}"

    @property
    def order_number(self) -> str:
        """Short human-readable order reference (first 8 hex chars, uppercased)."""
        return str(self.reference)[:8].upper()

    @property
    def total_display(self):
        return f"£{self.total_pence / 100:.2f}"

    @property
    def total_refunded_pence(self) -> int:
        """Sum of all succeeded refunds against this order."""
        result = self.refunds.filter(status="succeeded").aggregate(
            total=models.Sum("amount_pence")
        )
        return result["total"] or 0

    @property
    def remaining_refundable_pence(self) -> int:
        """Amount still available to refund (always >= 0)."""
        return max(0, self.total_pence - self.total_refunded_pence)

    @property
    def remaining_refundable_display(self) -> str:
        return f"£{self.remaining_refundable_pence / 100:.2f}"


class OrderItem(models.Model):
    """
    One line item within an Order.
    Polymorphic: either a booking slot or a physical product.
    """

    ITEM_TYPE_BOOKING = "booking"
    ITEM_TYPE_PRODUCT = "product"
    ITEM_TYPE_PACKAGE = "package"
    ITEM_TYPE_CHOICES = [
        (ITEM_TYPE_BOOKING, "Booking"),
        (ITEM_TYPE_PRODUCT, "Product"),
        (ITEM_TYPE_PACKAGE, "Package"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_type = models.CharField(
        max_length=10,
        choices=ITEM_TYPE_CHOICES,
        default=ITEM_TYPE_BOOKING,
        db_index=True,
    )

    # --- Booking fields (null when item_type = product) ---
    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    session_type = models.ForeignKey(
        "booking.SessionType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    location = models.ForeignKey(
        "booking.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    # --- Product fields (null when item_type = booking) ---
    product = models.ForeignKey(
        "shop.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(default=1)

    # --- Package fields (null when item_type != package) ---
    package = models.ForeignKey(
        "booking.Package",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_items",
    )

    # --- Common fields ---
    price_pence = models.PositiveIntegerField()
    label = models.CharField(max_length=255)

    # --- Fulfilment (products only) ---
    shipped = models.BooleanField(
        default=False,
        help_text="Mark True once a physical product has been dispatched. "
                  "Auto-restock is skipped for shipped items on refund.",
    )

    class Meta:
        ordering = ["item_type", "label"]

    def __str__(self):
        return self.label

    @property
    def line_total_pence(self):
        return self.price_pence * self.quantity

    @property
    def is_booking(self):
        return self.item_type == self.ITEM_TYPE_BOOKING

    @property
    def is_product(self):
        return self.item_type == self.ITEM_TYPE_PRODUCT

    def validate(self):
        """
        Assert that the right FK fields are populated for this item_type.

        Call this in tests and in _create_*_order_item helpers to catch
        schema violations early — before they silently produce broken orders.
        Raises AssertionError with a descriptive message on failure.

        When a third item type (e.g. package, gift card) is added, extend
        this method rather than scattering isinstance/item_type checks.
        """
        pk_label = f"OrderItem pk={self.pk}" if self.pk else "unsaved OrderItem"

        if self.item_type == self.ITEM_TYPE_BOOKING:
            assert self.product_id is None, (
                f"{pk_label}: booking item must not have product_id set "
                f"(got product_id={self.product_id})"
            )
            has_booking = self.booking_id is not None
            has_snapshot = self.session_type_id is not None and self.date is not None
            assert has_booking or has_snapshot, (
                f"{pk_label}: booking item must have either a booking FK "
                f"or a session_type + date snapshot"
            )

        elif self.item_type == self.ITEM_TYPE_PRODUCT:
            assert self.product_id is not None, (
                f"{pk_label}: product item must have product_id set"
            )
            assert self.booking_id is None, (
                f"{pk_label}: product item must not have booking_id set "
                f"(got booking_id={self.booking_id})"
            )

        elif self.item_type == self.ITEM_TYPE_PACKAGE:
            assert self.package_id is not None, (
                f"{pk_label}: package item must have package_id set"
            )
            assert self.booking_id is None and self.product_id is None, (
                f"{pk_label}: package item must not have booking or product set"
            )

        else:
            raise AssertionError(
                f"{pk_label}: unknown item_type '{self.item_type}' — "
                f"update OrderItem.validate() when adding new item types"
            )


# =============================================================================
# Payment audit log
# =============================================================================

class PaymentRecord(models.Model):
    """
    Immutable log of every Stripe event we process.
    One row per event — never updated, only created.
    """

    EVENT_TYPES = [
        ("checkout.session.completed", "Checkout completed"),
        ("payment_intent.payment_failed", "Payment failed"),
        ("charge.refunded", "Refunded"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="payment_records",
        null=True,
        blank=True,
    )
    order_reference = models.CharField(max_length=36, db_index=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    stripe_event_id = models.CharField(max_length=255, unique=True)
    amount_pence = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="GBP")
    raw_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} — {self.stripe_event_id}"


# =============================================================================
# Voucher / discount codes
# =============================================================================

class Voucher(models.Model):
    """
    Discount or session-credit code.

    Three discount types:
    - percentage  → e.g. 10% off the subtotal
    - fixed_pence → e.g. 500 = £5.00 off
    - full        → zeroes the matched line entirely (used for package credits
                    and complimentary friend passes)

    Restrictions (all nullable = unrestricted):
    - allowed_email   → only the holder of this email may redeem it
    - session_type    → only valid for this session type
    - location        → only valid at this pool; if set and cart uses a
                        different pool, a location-specific error is returned
                        so the client knows to switch pools rather than
                        treating the code as invalid
    - package_purchase → links a generated credit code back to its purchase
    """

    DISCOUNT_PERCENTAGE = "percentage"
    DISCOUNT_FIXED = "fixed_pence"
    DISCOUNT_FULL = "full"
    DISCOUNT_TYPES = [
        (DISCOUNT_PERCENTAGE, "Percentage"),
        (DISCOUNT_FIXED, "Fixed amount (pence)"),
        (DISCOUNT_FULL, "Full (zeroes the line)"),
    ]

    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPES)
    discount_value = models.PositiveIntegerField(
        default=0,
        help_text="Percentage (e.g. 10 for 10%) or pence amount. Unused for 'full' type.",
    )

    # --- Restrictions ---
    allowed_email = models.EmailField(
        null=True,
        blank=True,
        help_text="If set, only this email address may redeem the code.",
    )
    session_type = models.ForeignKey(
        "booking.SessionType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vouchers",
        help_text="If set, code only applies to this session type.",
    )
    location = models.ForeignKey(
        "booking.Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vouchers",
        help_text="If set, code only applies at this pool.",
    )
    package_purchase = models.ForeignKey(
        "PackagePurchase",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="vouchers",
        help_text="Set when this code was generated from a package purchase.",
    )

    # --- Usage limits ---
    max_uses = models.PositiveIntegerField(
        default=0,
        help_text="0 = unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0)

    # --- Validity ---
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Null = no expiry.")
    min_order_pence = models.PositiveIntegerField(
        default=0,
        help_text="Minimum cart total before this voucher applies.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def is_valid(self, subtotal_pence: int = 0) -> bool:
        """Check active, dates, usage cap, and minimum order."""
        if not self.is_active:
            return False
        now = timezone.now()
        if now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.max_uses and self.times_used >= self.max_uses:
            return False
        if subtotal_pence < self.min_order_pence:
            return False
        return True

    def calculate_discount(self, subtotal_pence: int) -> int:
        """Return discount in pence, capped at the subtotal."""
        if self.discount_type == self.DISCOUNT_FULL:
            return subtotal_pence
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            return min(int(subtotal_pence * self.discount_value / 100), subtotal_pence)
        return min(self.discount_value, subtotal_pence)

    def redeem(self):
        """
        Increment usage counter atomically via F() expression — prevents the
        read-modify-write race where two concurrent checkouts both see
        times_used=0 and both write 1.
        """
        from django.db.models import F
        Voucher.objects.filter(pk=self.pk).update(times_used=F("times_used") + 1)
        self.refresh_from_db(fields=["times_used"])


# =============================================================================
# Package purchases
# =============================================================================

class PackagePurchase(models.Model):
    """
    A client buying a multi-session package.

    Credits remaining are tracked by the related Voucher rows (one per session).
    Voucher.times_used == 0 → unused credit.  This keeps a single source of
    truth and lets each credit be redeemed atomically via Voucher.redeem().
    """

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    package = models.ForeignKey(
        "booking.Package",
        on_delete=models.PROTECT,
        related_name="purchases",
    )

    # Client identity — email is the canonical audit record.
    # user is linked at purchase time if logged in, or later via migration
    # when a guest registers with the same email.
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="package_purchases",
    )
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()

    amount_pence = models.PositiveIntegerField()
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    purchased_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-purchased_at"]

    def __str__(self):
        return f"{self.package.name} — {self.client_email}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def credits_remaining(self) -> int:
        """Unused voucher rows for this purchase. Single source of truth."""
        return self.vouchers.filter(times_used=0, is_active=True).count()

    @property
    def is_usable(self) -> bool:
        return self.is_active and not self.is_expired and self.credits_remaining > 0


# =============================================================================
# Payment reminder rules  (owner-configurable schedule)
# =============================================================================

class PaymentReminderRule(models.Model):
    """
    One entry in the owner-defined reminder schedule.

    Two anchor types:
    • ANCHOR_CREATED  — fires N hours after the booking was created.
    • ANCHOR_SESSION  — fires when fewer than N hours remain before the session.

    The django_q2 task evaluates all active rules independently on each run.
    Each rule fires at most once per booking (enforced via PaymentReminder's
    unique constraint).
    """

    ANCHOR_CREATED = "created"
    ANCHOR_SESSION = "session"
    ANCHOR_CHOICES = [
        (ANCHOR_CREATED, "After booking created"),
        (ANCHOR_SESSION, "Before session date"),
    ]

    delay_hours = models.PositiveIntegerField(
        help_text="Number of hours relative to the chosen anchor.",
    )
    delay_anchor = models.CharField(
        max_length=10,
        choices=ANCHOR_CHOICES,
        default=ANCHOR_CREATED,
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in settings.",
    )

    class Meta:
        ordering = ["order", "delay_anchor", "delay_hours"]
        verbose_name = "Payment reminder rule"
        verbose_name_plural = "Payment reminder rules"

    def __str__(self):
        anchor_label = self.get_delay_anchor_display()
        if self.delay_anchor == self.ANCHOR_CREATED:
            return f"+{self.delay_hours}h {anchor_label.lower()}"
        return f"{self.delay_hours}h {anchor_label.lower()}"


# =============================================================================
# Payment reminder log  (immutable audit — one row per email sent)
# =============================================================================

class PaymentReminder(models.Model):
    """
    Immutable record of every payment-reminder email sent.

    Never updated — only created.  Mirrors the same append-only philosophy
    as PaymentRecord.

    source=auto  → sent by the django_q2 task, rule is set.
    source=manual → sent by the owner from the dashboard, rule is null,
                    sent_by is the User who clicked the button.
    """

    SOURCE_AUTO   = "auto"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_AUTO,   "Automated"),
        (SOURCE_MANUAL, "Manual"),
    ]

    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.CASCADE,
        related_name="payment_reminders",
    )
    rule = models.ForeignKey(
        PaymentReminderRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
        help_text="Which rule triggered this send. Null for manual sends.",
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    sent_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The owner who manually triggered this send.",
    )
    email_sent_to = models.EmailField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "Payment reminder"
        verbose_name_plural = "Payment reminders"
        constraints = [
            # Each rule fires at most once per booking.
            # Manual sends (rule=None) are unconstrained.
            models.UniqueConstraint(
                fields=["booking", "rule"],
                condition=models.Q(rule__isnull=False),
                name="unique_reminder_per_rule_per_booking",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_source_display()} reminder → "
            f"{self.email_sent_to} ({self.sent_at:%d %b %Y %H:%M})"
        )


# =============================================================================
# Refund  (owner-initiated via dashboard — one row per Stripe refund)
# =============================================================================

class Refund(models.Model):
    """
    Immutable audit record for every refund issued through the dashboard.

    One row per Stripe refund.  Never updated after creation — mirrors the
    same append-only philosophy as PaymentRecord and PaymentReminder.

    The corresponding Order is flipped to STATUS_REFUNDED by the refund service
    after this record is written.
    """

    REASON_REQUESTED  = "requested_by_customer"
    REASON_DUPLICATE  = "duplicate"
    REASON_FRAUDULENT = "fraudulent"
    REASON_CHOICES = [
        (REASON_REQUESTED,  "Requested by customer"),
        (REASON_DUPLICATE,  "Duplicate charge"),
        (REASON_FRAUDULENT, "Fraudulent charge"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="refunds",
    )
    order_item = models.ForeignKey(
        "OrderItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refunds",
        help_text="The specific line item this refund covers. "
                  "Null for custom-amount or full-order refunds.",
    )
    stripe_refund_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,  # looked up on every charge.refund.updated webhook
        help_text="Stripe re_xxx identifier.",
    )
    amount_pence = models.PositiveIntegerField(
        help_text="Actual amount refunded (may differ from order total for partial refunds).",
    )
    reason = models.CharField(
        max_length=30,
        choices=REASON_CHOICES,
        default=REASON_REQUESTED,
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal notes visible only in the dashboard.",
    )
    status = models.CharField(
        max_length=20,
        default="pending",
        help_text="Stripe refund status: succeeded | pending | failed.",
    )
    initiated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The owner who clicked Refund in the dashboard.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Refund"
        verbose_name_plural = "Refunds"

    def __str__(self):
        return f"Refund {self.stripe_refund_id or '—'} — £{self.amount_pence / 100:.2f} ({self.status})"

    @property
    def amount_display(self) -> str:
        return f"£{self.amount_pence / 100:.2f}"
