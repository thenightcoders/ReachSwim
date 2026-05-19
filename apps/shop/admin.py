from django.contrib import admin
from apps.pages.admin import SingletonAdmin
from .models import ProductCategory, Product, ShopSettings


# =============================================================================
# Product Category
# =============================================================================

@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order", "product_count")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = "Products"


# =============================================================================
# Product
# =============================================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "color", "category", "price_display",
        "stock", "is_active", "order",
    )
    list_filter = ("category", "is_active")
    list_editable = ("stock", "is_active", "order")
    prepopulated_fields = {"slug": ("name", "color")}
    search_fields = ("name", "color", "description")
    ordering = ("order", "name")

    fieldsets = (
        (None, {
            "fields": (
                "name", "slug", "category", "color",
                "description", "price_pence",
            ),
        }),
        ("Media", {
            "fields": ("image", "photo_class"),
        }),
        ("Inventory", {
            "fields": ("stock", "is_active", "order"),
        }),
    )

    def price_display(self, obj):
        return obj.price_display
    price_display.short_description = "Price"


# =============================================================================
# Shop Settings (singleton)
# =============================================================================

@admin.register(ShopSettings)
class ShopSettingsAdmin(SingletonAdmin):
    fieldsets = (
        ("Section copy", {
            "fields": (
                "kicker", "heading", "heading_emphasis", "subheading",
            ),
        }),
        ("Shipping", {
            "fields": (
                "free_shipping_threshold_pence",
                "shipping_rate_pence",
                "free_shipping_note",
            ),
        }),
    )
