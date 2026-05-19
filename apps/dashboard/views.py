"""
Owner dashboard views.

Each view handles one section of the admin panel.
All gated behind @owner_required.
"""
import datetime

from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import owner_required


# ---------------------------------------------------------------------------
# Home — overview / stats
# ---------------------------------------------------------------------------

@owner_required
def home(request):
    """Dashboard home — quick stats and upcoming bookings."""
    from apps.booking.models import Booking
    from apps.payments.models import Order

    today = timezone.now().date()
    week_start = today - datetime.timedelta(days=today.weekday())

    # Quick stats
    upcoming_bookings = Booking.objects.filter(
        date__gte=today,
        status__in=["pending", "confirmed"],
    ).select_related("session_type", "location").order_by("date", "start_time")[:10]

    today_count = Booking.objects.filter(
        date=today, status="confirmed",
    ).count()

    week_revenue = Order.objects.filter(
        status="paid",
        created_at__date__gte=week_start,
    ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("total_pence"))["total"] or 0

    pending_orders = Order.objects.filter(status="pending").count()

    return render(request, "dashboard/home.html", {
        "upcoming_bookings": upcoming_bookings,
        "today_count": today_count,
        "week_revenue": week_revenue,
        "pending_orders": pending_orders,
        "section": "home",
    })


# ---------------------------------------------------------------------------
# Bookings management
# ---------------------------------------------------------------------------

@owner_required
def bookings(request):
    """List all bookings with filters."""
    from apps.booking.models import Booking

    status = request.GET.get("status", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    qs = Booking.objects.select_related(
        "session_type", "location",
    ).order_by("-date", "-start_time")

    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    return render(request, "dashboard/bookings.html", {
        "bookings": qs[:100],
        "current_status": status,
        "date_from": date_from,
        "date_to": date_to,
        "section": "bookings",
    })


@owner_required
def booking_detail(request, pk):
    """View a single booking with edit capability."""
    from apps.booking.models import Booking

    booking = get_object_or_404(Booking, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm" and booking.status == "pending":
            booking.status = Booking.STATUS_CONFIRMED
            booking.save(update_fields=["status", "updated_at"])
        elif action == "cancel" and booking.status in ("pending", "confirmed"):
            booking.status = Booking.STATUS_CANCELLED
            booking.cancelled_at = timezone.now()
            booking.cancellation_reason = request.POST.get("reason", "")
            booking.save(update_fields=[
                "status", "cancelled_at", "cancellation_reason", "updated_at",
            ])
        elif action == "complete" and booking.status == "confirmed":
            booking.status = Booking.STATUS_COMPLETED
            booking.save(update_fields=["status", "updated_at"])
        elif action == "save_notes":
            booking.notes = request.POST.get("notes", "")
            booking.save(update_fields=["notes", "updated_at"])
        return redirect("dashboard:booking_detail", pk=pk)

    return render(request, "dashboard/booking_detail.html", {
        "booking": booking,
        "section": "bookings",
    })


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@owner_required
def orders(request):
    """List all orders."""
    from apps.payments.models import Order

    status = request.GET.get("status", "")
    qs = Order.objects.prefetch_related("items").order_by("-created_at")

    if status:
        qs = qs.filter(status=status)

    return render(request, "dashboard/orders.html", {
        "orders": qs[:100],
        "current_status": status,
        "section": "orders",
    })


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@owner_required
def products(request):
    """List all products with inline stock editing."""
    from apps.shop.models import Product

    products = Product.objects.select_related("category").order_by("order", "name")

    return render(request, "dashboard/products.html", {
        "products": products,
        "section": "products",
    })


@owner_required
@require_POST
def product_update_stock(request, pk):
    """Quick stock update from the products list."""
    from apps.shop.models import Product

    product = get_object_or_404(Product, pk=pk)
    try:
        stock = int(request.POST.get("stock", 0))
        product.stock = max(0, stock)
        product.save(update_fields=["stock"])
    except (ValueError, TypeError):
        pass
    return redirect("dashboard:products")


@owner_required
@require_POST
def product_toggle_active(request, pk):
    """Toggle product active/inactive."""
    from apps.shop.models import Product

    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    return redirect("dashboard:products")


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------

@owner_required
def settings_view(request):
    """Edit site settings, hero, shop settings — all singletons in one page."""
    from apps.pages.models import SiteConfig, HeroSection
    from apps.booking.models import BookingSettings
    from apps.shop.models import ShopSettings

    site = SiteConfig.load()
    hero = HeroSection.load()
    booking_settings = BookingSettings.load()
    shop_settings = ShopSettings.load()

    if request.method == "POST":
        section = request.POST.get("_section")

        if section == "site":
            for field in ["site_name", "tagline", "email", "phone",
                          "location_text", "meta_description",
                          "whatsapp_url", "instagram_url"]:
                if field in request.POST:
                    setattr(site, field, request.POST[field])
            if "established_year" in request.POST:
                try:
                    site.established_year = int(request.POST["established_year"])
                except ValueError:
                    pass
            site.save()

        elif section == "hero":
            for field in ["headline", "subheadline",
                          "cta_primary_text", "cta_secondary_text", "strip_items"]:
                if field in request.POST:
                    setattr(hero, field, request.POST[field])
            site.save()
            hero.save()

        elif section == "booking":
            for field in ["booking_page_heading", "booking_page_subheading"]:
                if field in request.POST:
                    setattr(booking_settings, field, request.POST[field])
            for int_field in ["max_advance_days", "min_advance_hours",
                              "cancellation_hours", "slot_duration_minutes"]:
                if int_field in request.POST:
                    try:
                        setattr(booking_settings, int_field, int(request.POST[int_field]))
                    except ValueError:
                        pass
            booking_settings.save()

        elif section == "shop":
            for field in ["kicker", "heading", "heading_emphasis",
                          "subheading", "free_shipping_note"]:
                if field in request.POST:
                    setattr(shop_settings, field, request.POST[field])
            for int_field in ["free_shipping_threshold_pence", "shipping_rate_pence"]:
                if int_field in request.POST:
                    try:
                        setattr(shop_settings, int_field, int(request.POST[int_field]))
                    except ValueError:
                        pass
            shop_settings.save()

        return redirect("dashboard:settings")

    return render(request, "dashboard/settings.html", {
        "site": site,
        "hero": hero,
        "booking_settings": booking_settings,
        "shop_settings": shop_settings,
        "section": "settings",
    })


# ---------------------------------------------------------------------------
# Messages (contact form)
# ---------------------------------------------------------------------------

@owner_required
def messages_view(request):
    """View contact form messages."""
    from apps.legal.models import ContactMessage

    msgs = ContactMessage.objects.order_by("-created_at")[:50]

    return render(request, "dashboard/messages.html", {
        "messages_list": msgs,
        "section": "messages",
    })


@owner_required
@require_POST
def message_mark_read(request, pk):
    """Mark a message as read."""
    from apps.legal.models import ContactMessage

    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_read = True
    msg.save(update_fields=["is_read"])
    return redirect("dashboard:messages")
