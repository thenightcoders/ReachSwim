"""
Payment models.

Order + OrderItem group one or more bookings into a single checkout.
PaymentRecord logs every Stripe event for audit.
Voucher handles discount codes.
PackagePurchase tracks multi-session bundles.
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
    def total_display(self):
        return f"£{self.total_pence / 100:.2f}"


class OrderItem(models.Model):
    """
    One line item within an Order.
    Polymorphic: either a booking slot or a physical product.
    """

    ITEM_TYPE_BOOKING = "booking"
    ITEM_TYPE_PRODUCT = "product"
    ITEM_TYPE_CHOICES = [
        (ITEM_TYPE_BOOKING, "Booking"),
        (ITEM_TYPE_PRODUCT, "Product"),
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

    # --- Common fields ---
    price_pence = models.PositiveIntegerField()
    label = models.CharField(max_length=255)

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
    """Discount code — percentage or fixed-pence off."""

    DISCOUNT_PERCENTAGE = "percentage"
    DISCOUNT_FIXED = "fixed_pence"
    DISCOUNT_TYPES = [
        (DISCOUNT_PERCENTAGE, "Percentage"),
        (DISCOUNT_FIXED, "Fixed amount (pence)"),
    ]

    code = models.CharField(max_length=30, unique=True)
    discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPES)
    discount_value = models.PositiveIntegerField(
        help_text="Percentage (e.g. 10 for 10%) or pence amount.",
    )
    max_uses = models.PositiveIntegerField(
        default=0,
        help_text="0 = unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
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
        """Check all constraints: active, dates, usage, minimum order."""
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
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            discount = int(subtotal_pence * self.discount_value / 100)
        else:
            discount = self.discount_value
        return min(discount, subtotal_pence)

    def redeem(self):
        """Increment usage counter."""
        self.times_used += 1
        self.save(update_fields=["times_used"])


# =============================================================================
# Package purchases
# =============================================================================

class PackagePurchase(models.Model):
    """
    A client buying a multi-session package.
    Sessions are deducted as they book using the package.
    """

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    package = models.ForeignKey(
        "booking.Package",
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    sessions_remaining = models.PositiveIntegerField()
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
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        return self.is_active and not self.is_expired and self.sessions_remaining > 0

    def use_session(self):
        """Deduct one session. Raises ValueError if none left."""
        if self.sessions_remaining <= 0:
            raise ValueError("No sessions remaining on this package.")
        self.sessions_remaining -= 1
        if self.sessions_remaining == 0:
            self.is_active = False
        self.save(update_fields=["sessions_remaining", "is_active"])
