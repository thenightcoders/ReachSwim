from django.contrib import admin, messages
from django.utils.html import format_html
from apps.pages.admin import SingletonAdmin
from .models import (
    BookingSettings,
    SessionType,
    Location,
    SessionPricing,
    Package,
    RecurringSchedule,
    GoogleCalendarConfig,
    Booking,
)


# =============================================================================
# Booking Settings (singleton)
# =============================================================================

@admin.register(BookingSettings)
class BookingSettingsAdmin(SingletonAdmin):
    fieldsets = (
        ("Limits", {
            "fields": (
                "max_advance_days",
                "min_advance_hours",
                "cancellation_hours",
                "slot_duration_minutes",
            ),
        }),
        ("Page copy", {
            "fields": ("booking_page_heading", "booking_page_subheading"),
        }),
    )


# =============================================================================
# Session Types  (with pricing inline)
# =============================================================================

class SessionPricingInline(admin.TabularInline):
    model = SessionPricing
    extra = 1
    fields = ("location", "price_pence")


class PackageInline(admin.TabularInline):
    model = Package
    extra = 0
    fields = ("name", "session_count", "price_pence", "valid_days", "is_active", "order")


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "duration_minutes", "max_participants", "is_active", "order")
    list_editable = ("is_active", "order")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SessionPricingInline, PackageInline]
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "description"),
        }),
        ("Settings", {
            "fields": ("duration_minutes", "max_participants", "is_active", "order"),
        }),
    )


# =============================================================================
# Locations  (with pricing inline from the other side)
# =============================================================================

class LocationPricingInline(admin.TabularInline):
    """Same model, different inline — view pricing from the location side."""
    model = SessionPricing
    extra = 1
    fields = ("session_type", "price_pence")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "address_short", "has_parking", "has_hoist", "is_active", "order")
    list_editable = ("is_active", "order")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [LocationPricingInline]
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "address", "description"),
        }),
        ("Facilities", {
            "fields": ("has_parking", "has_hoist"),
        }),
        ("Status", {
            "fields": ("is_active", "order"),
        }),
    )

    @admin.display(description="Address")
    def address_short(self, obj):
        return obj.address[:60] + "..." if len(obj.address) > 60 else obj.address


# =============================================================================
# Session Pricing (standalone — also accessible as inlines above)
# =============================================================================

@admin.register(SessionPricing)
class SessionPricingAdmin(admin.ModelAdmin):
    list_display = ("session_type", "location", "price_display")
    list_filter = ("session_type", "location")
    search_fields = ("session_type__name", "location__name")
    ordering = ("session_type__name", "location__name")


# =============================================================================
# Packages  (standalone list — also available as inline on SessionType)
# =============================================================================

@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = (
        "name", "session_type", "session_count",
        "price_display", "per_session_display",
        "valid_days", "is_active", "order",
    )
    list_editable = ("is_active", "order")
    list_filter = ("session_type", "is_active")


# =============================================================================
# Recurring Schedules
# =============================================================================

@admin.register(RecurringSchedule)
class RecurringScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "session_type", "location", "get_day_display",
        "start_time", "end_time", "max_capacity", "is_active",
    )
    list_editable = ("is_active",)
    list_filter = ("session_type", "location", "day_of_week", "is_active")
    ordering = ("day_of_week", "start_time")

    @admin.display(description="Day", ordering="day_of_week")
    def get_day_display(self, obj):
        return obj.get_day_of_week_display()


# =============================================================================
# Google Calendar (singleton)
# =============================================================================

@admin.register(GoogleCalendarConfig)
class GoogleCalendarConfigAdmin(SingletonAdmin):
    fieldsets = (
        (None, {
            "fields": ("calendar_id", "is_connected", "last_synced"),
        }),
        ("Credentials", {
            "fields": ("credentials_json",),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("is_connected", "last_synced")


# =============================================================================
# Bookings
# =============================================================================

# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------

@admin.action(description="Confirm selected bookings")
def confirm_bookings(modeladmin, request, queryset):
    from apps.booking.services.booking import confirm_booking

    confirmable = queryset.filter(status=Booking.STATUS_PENDING)
    count = 0
    for booking in confirmable:
        confirm_booking(booking)
        count += 1

    if count:
        modeladmin.message_user(
            request,
            f"{count} booking(s) confirmed and confirmation emails sent.",
            messages.SUCCESS,
        )
    else:
        modeladmin.message_user(
            request,
            "No pending bookings in the selection.",
            messages.WARNING,
        )


@admin.action(description="Cancel selected bookings")
def cancel_bookings(modeladmin, request, queryset):
    from apps.booking.services.booking import cancel_booking

    cancellable = queryset.exclude(
        status__in=(Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED)
    )
    count = 0
    for booking in cancellable:
        cancel_booking(booking, reason="Cancelled by admin.")
        count += 1

    if count:
        modeladmin.message_user(
            request,
            f"{count} booking(s) cancelled.",
            messages.SUCCESS,
        )
    else:
        modeladmin.message_user(
            request,
            "No cancellable bookings in the selection.",
            messages.WARNING,
        )


@admin.action(description="Mark selected bookings as completed")
def complete_bookings(modeladmin, request, queryset):
    from apps.booking.services.booking import complete_booking

    completable = queryset.filter(status=Booking.STATUS_CONFIRMED)
    count = completable.count()
    for booking in completable:
        complete_booking(booking)

    if count:
        modeladmin.message_user(
            request,
            f"{count} booking(s) marked as completed.",
            messages.SUCCESS,
        )
    else:
        modeladmin.message_user(
            request,
            "No confirmed bookings in the selection.",
            messages.WARNING,
        )


@admin.action(description="Re-send confirmation email to selected clients")
def resend_confirmation_emails(modeladmin, request, queryset):
    from apps.booking.services.email import send_booking_confirmation

    sent = 0
    failed = 0
    for booking in queryset.filter(status=Booking.STATUS_CONFIRMED):
        ok = send_booking_confirmation(booking)
        if ok:
            sent += 1
        else:
            failed += 1

    parts = []
    if sent:
        parts.append(f"{sent} email(s) sent")
    if failed:
        parts.append(f"{failed} failed (check logs)")

    level = messages.SUCCESS if not failed else messages.WARNING
    modeladmin.message_user(request, "; ".join(parts) or "No confirmed bookings selected.", level)


# ---------------------------------------------------------------------------
# BookingAdmin
# ---------------------------------------------------------------------------

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "reference_short", "session_type", "location",
        "date", "start_time", "client_name",
        "status_badge", "amount_display", "is_cancellable_display",
    )
    list_filter = ("status", "session_type", "location", "date")
    search_fields = ("client_name", "client_email", "reference")
    readonly_fields = (
        "reference", "created_at", "updated_at",
        "stripe_payment_intent_id", "google_event_id",
    )
    date_hierarchy = "date"
    ordering = ("-date", "-start_time")
    actions = [confirm_bookings, cancel_bookings, complete_bookings, resend_confirmation_emails]

    fieldsets = (
        ("Session", {
            "fields": ("reference", "session_type", "location", "date", "start_time", "end_time"),
        }),
        ("Client", {
            "fields": ("client_name", "client_email", "client_phone"),
        }),
        ("Status & Payment", {
            "fields": (
                "status", "amount_pence",
                "stripe_payment_intent_id",
                "is_refunded", "refunded_amount_pence",
            ),
        }),
        ("Integrations", {
            "fields": ("google_event_id",),
            "classes": ("collapse",),
        }),
        ("Cancellation", {
            "fields": ("cancelled_at", "cancellation_reason"),
            "classes": ("collapse",),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Ref")
    def reference_short(self, obj):
        return str(obj.reference)[:8]

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            Booking.STATUS_PENDING:   "#f59e0b",
            Booking.STATUS_CONFIRMED: "#10b981",
            Booking.STATUS_CANCELLED: "#ef4444",
            Booking.STATUS_COMPLETED: "#6366f1",
        }
        colour = colours.get(obj.status, "#888")
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:9999px;'
            'background:{};color:#fff;font-size:11px;font-weight:600">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Cancellable?", boolean=True)
    def is_cancellable_display(self, obj):
        return obj.is_cancellable
