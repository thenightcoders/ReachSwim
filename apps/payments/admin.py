from django.contrib import admin
from apps.payments.models import (
    Order,
    OrderItem,
    PackagePurchase,
    PaymentRecord,
    Voucher,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "item_type", "booking", "session_type", "location", "date",
        "start_time", "end_time", "product", "quantity",
        "price_pence", "label",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentRecordInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0
    readonly_fields = (
        "event_type", "stripe_event_id", "amount_pence",
        "currency", "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Model admins
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "client_name", "client_email", "total_display",
        "status", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("reference", "client_name", "client_email")
    readonly_fields = (
        "reference", "created_at", "updated_at",
        "stripe_payment_intent_id",
    )
    inlines = [OrderItemInline, PaymentRecordInline]


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "stripe_event_id", "event_type", "order_reference",
        "amount_pence", "currency", "created_at",
    )
    list_filter = ("event_type", "created_at")
    search_fields = ("stripe_event_id", "order_reference")
    readonly_fields = (
        "order", "order_reference", "event_type", "stripe_event_id",
        "amount_pence", "currency", "raw_payload", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = (
        "code", "discount_type", "discount_value", "times_used",
        "max_uses", "is_active", "valid_from", "valid_until",
    )
    list_filter = ("discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("times_used", "created_at")


@admin.register(PackagePurchase)
class PackagePurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "package", "client_email",
        "sessions_remaining", "is_active", "expires_at",
    )
    list_filter = ("is_active", "package")
    search_fields = ("client_email", "client_name", "reference")
    readonly_fields = ("reference", "purchased_at", "stripe_payment_intent_id")
