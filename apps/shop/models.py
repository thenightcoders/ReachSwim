"""
Shop models.

Product — a physical item (cap, goggles, etc.).
ProductCategory — grouping for filter tabs.
ShopSettings — singleton for shipping config + section copy.
"""
from django.db import models
from apps.pages.models import SingletonModel


# =============================================================================
# Product category
# =============================================================================

class ProductCategory(models.Model):
    """Filter group: Caps, Goggles, etc."""

    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first in filter tabs.",
    )

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name


# =============================================================================
# Product
# =============================================================================

class Product(models.Model):
    """A physical product — cap, goggles, etc."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="products",
    )
    description = models.TextField(
        blank=True,
        help_text="Short description shown on product card.",
    )
    color = models.CharField(
        max_length=60,
        blank=True,
        help_text="e.g. 'Reef Blue', 'Smoke'. Shown below product name.",
    )
    price_pence = models.PositiveIntegerField(
        help_text="Price in pence (e.g. 2400 = £24.00).",
    )
    image = models.ImageField(
        upload_to="shop/products/",
        blank=True,
        help_text="Product photo. Square aspect ratio recommended.",
    )
    photo_class = models.CharField(
        max_length=40,
        blank=True,
        help_text="CSS class for placeholder gradient (e.g. 'photo--tile'). "
                  "Used when no image is uploaded.",
    )
    stock = models.PositiveIntegerField(
        default=0,
        help_text="0 = out of stock.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within category.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.name} — {self.color}" if self.color else self.name

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def price_display(self):
        return f"£{self.price_pence / 100:.2f}"


# =============================================================================
# Shop settings (singleton)
# =============================================================================

class ShopSettings(SingletonModel):
    """Admin-configurable shop section settings."""

    # Section copy
    kicker = models.CharField(max_length=60, default="The shop")
    heading = models.CharField(max_length=200, default="Caps & goggles.")
    heading_emphasis = models.CharField(
        max_length=200,
        default="That's it.",
        help_text="Italic/emphasis part of the heading.",
    )
    subheading = models.TextField(
        default="Two things, done right. Tested in Maren's own lane "
                "before they hit the shelves.",
        help_text="Shown to the right of the heading.",
    )

    # Shipping
    free_shipping_threshold_pence = models.PositiveIntegerField(
        default=5000,
        help_text="Cart total (pence) above which shipping is free. "
                  "e.g. 5000 = £50.00.",
    )
    shipping_rate_pence = models.PositiveIntegerField(
        default=600,
        help_text="Flat shipping rate in pence when below threshold. "
                  "e.g. 600 = £6.00.",
    )
    free_shipping_note = models.CharField(
        max_length=200,
        default="Free shipping on £50+.",
        help_text="Shown in the shop section header.",
    )

    class Meta:
        verbose_name = "Shop settings"
        verbose_name_plural = "Shop settings"

    def __str__(self):
        return "Shop Settings"

    def shipping_cost(self, product_total_pence: int) -> int:
        """Return shipping cost for a given product subtotal."""
        if product_total_pence >= self.free_shipping_threshold_pence:
            return 0
        return self.shipping_rate_pence
