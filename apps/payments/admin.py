from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone
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
# Admin actions
# ---------------------------------------------------------------------------

@admin.action(description="Expire selected pending orders (cancel bookings)")
def expire_selected_orders(modeladmin, request, queryset):
    from apps.payments.services.checkout import cancel_pending_order

    pending = queryset.filter(status=Order.STATUS_PENDING)
    count = 0
    for order in pending:
        cancel_pending_order(str(order.reference))
        count += 1

    if count:
        modeladmin.message_user(
            request,
            f"{count} pending order(s) expired and bookings released.",
            messages.SUCCESS,
        )
    else:
        modeladmin.message_user(request, "No pending orders in the selection.", messages.WARNING)


@admin.action(description="Deactivate selected vouchers")
def deactivate_vouchers(modeladmin, request, queryset):
    count = queryset.filter(is_active=True).update(is_active=False)
    modeladmin.message_user(
        request,
        f"{count} voucher(s) deactivated.",
        messages.SUCCESS if count else messages.WARNING,
    )


@admin.action(description="Activate selected vouchers")
def activate_vouchers(modeladmin, request, queryset):
    count = queryset.filter(is_active=False).update(is_active=True)
    modeladmin.message_user(
        request,
        f"{count} voucher(s) activated.",
        messages.SUCCESS if count else messages.WARNING,
    )


@admin.action(description="Reset usage counter to 0")
def reset_voucher_usage(modeladmin, request, queryset):
    count = queryset.update(times_used=0)
    modeladmin.message_user(
        request,
        f"Usage counter reset for {count} voucher(s).",
        messages.SUCCESS,
    )


# ---------------------------------------------------------------------------
# Model admins
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference_short", "client_name", "client_email", "total_display",
        "status_badge", "item_count", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("reference", "client_name", "client_email", "voucher_code")
    readonly_fields = (
        "reference", "created_at", "updated_at",
        "stripe_payment_intent_id",
    )
    inlines = [OrderItemInline, PaymentRecordInline]
    actions = [expire_selected_orders]
    date_hierarchy = "created_at"

    @admin.display(description="Ref")
    def reference_short(self, obj):
        return str(obj.reference)[:8]

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            Order.STATUS_PENDING:  "#f59e0b",
            Order.STATUS_PAID:     "#10b981",
            Order.STATUS_REFUNDED: "#6366f1",
            Order.STATUS_EXPIRED:  "#ef4444",
        }
        colour = colours.get(obj.status, "#888")
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:9999px;'
            'background:{};color:#fff;font-size:11px;font-weight:600">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.items.count()


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
        "currently_valid",
    )
    list_filter = ("discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("times_used", "created_at")
    actions = [deactivate_vouchers, activate_vouchers, reset_voucher_usage]

    @admin.display(description="Valid now?", boolean=True)
    def currently_valid(self, obj):
        return obj.is_valid()


@admin.register(PackagePurchase)
class PackagePurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "reference_short", "package", "client_email",
        "sessions_remaining", "is_active", "expires_at", "is_usable_display",
    )
    list_filter = ("is_active", "package")
    search_fields = ("client_email", "client_name", "reference")
    readonly_fields = ("reference", "purchased_at", "stripe_payment_intent_id")

    @admin.display(description="Ref")
    def reference_short(self, obj):
        return str(obj.reference)[:8]

    @admin.display(description="Usable?", boolean=True)
    def is_usable_display(self, obj):
        return obj.is_usable
