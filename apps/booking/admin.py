from django.contrib import admin
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

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "reference_short", "session_type", "location",
        "date", "start_time", "client_name",
        "status", "amount_display",
    )
    list_filter = ("status", "session_type", "location", "date")
    search_fields = ("client_name", "client_email", "reference")
    readonly_fields = (
        "reference", "created_at", "updated_at",
        "stripe_payment_intent_id", "google_event_id",
    )
    date_hierarchy = "date"
    ordering = ("-date", "-start_time")

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
