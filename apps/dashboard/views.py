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
from apps.accounts.models import User


# ---------------------------------------------------------------------------
# Home — overview / stats
# ---------------------------------------------------------------------------

@owner_required
def home(request):
    """Dashboard home — quick stats and upcoming bookings."""
    from django.db.models import Sum
    from apps.booking.models import Booking
    from apps.payments.models import Order
    from apps.legal.models import ContactMessage

    today = timezone.now().date()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

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
    ).aggregate(total=Sum("total_pence"))["total"] or 0

    month_revenue = Order.objects.filter(
        status="paid",
        created_at__date__gte=month_start,
    ).aggregate(total=Sum("total_pence"))["total"] or 0

    pending_orders = Order.objects.filter(status="pending").count()

    # Count unique client emails across all bookings — includes guest checkouts,
    # not just registered User accounts with role=client.
    from apps.booking.models import Booking as _Booking
    total_clients = _Booking.objects.values("client_email").distinct().count()

    unread_messages = ContactMessage.objects.filter(is_read=False).count()

    return render(request, "dashboard/home.html", {
        "upcoming_bookings": upcoming_bookings,
        "today_count": today_count,
        "week_revenue": week_revenue,
        "month_revenue": month_revenue,
        "pending_orders": pending_orders,
        "total_clients": total_clients,
        "unread_messages": unread_messages,
        "section": "home",
    })


# ---------------------------------------------------------------------------
# Bookings management
# ---------------------------------------------------------------------------

@owner_required
def bookings(request):
    """List all bookings with filters."""
    from django.db.models import Q
    from apps.booking.models import Booking

    status = request.GET.get("status", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    q = request.GET.get("q", "").strip()

    qs = Booking.with_spots_taken().select_related(
        "session_type", "location",
    ).order_by("-date", "-start_time")

    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if q:
        qs = qs.filter(
            Q(client_name__icontains=q) | Q(client_email__icontains=q)
        )

    bookings_list = list(qs[:200])

    return render(request, "dashboard/bookings.html", {
        "bookings": bookings_list,
        "booking_count": len(bookings_list),
        "current_status": status,
        "date_from": date_from,
        "date_to": date_to,
        "q": q,
        "section": "bookings",
    })


@owner_required
def booking_detail(request, pk):
    """View a single booking with edit capability."""
    from apps.booking.models import Booking
    from apps.booking.services.booking import (
        confirm_booking,
        cancel_booking,
        complete_booking,
    )
    from apps.payments.models import Order

    booking = get_object_or_404(Booking, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm" and booking.status == Booking.STATUS_PENDING:
            confirm_booking(booking)
        elif action == "cancel" and booking.status in (
            Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED
        ):
            reason = request.POST.get("reason", "")
            cancel_booking(booking, reason=reason)
        elif action == "complete" and booking.status == Booking.STATUS_CONFIRMED:
            complete_booking(booking)
        elif action == "save_notes":
            booking.notes = request.POST.get("notes", "")
            booking.save(update_fields=["notes", "updated_at"])
        return redirect("dashboard:booking_detail", pk=pk)

    reminders = booking.payment_reminders.select_related("rule", "sent_by").order_by("-sent_at")
    last_reminder = reminders.first()

    # Pop the confirm flag that send_reminder sets when a resend needs confirmation.
    reminder_confirm = request.session.pop(f"reminder_confirm_{pk}", False)

    # Refund context — resolve associated paid order (if any).
    booking_order_item = booking.order_items.select_related("order").first()
    order = booking_order_item.order if booking_order_item else None

    # Has THIS specific booking item already been successfully refunded?
    booking_item_refund = (
        booking_order_item.refunds.filter(status="succeeded").first()
        if booking_order_item else None
    )
    remaining_pence = order.remaining_refundable_pence if order else 0
    can_refund = (
        order is not None
        and bool(order.stripe_payment_intent_id)
        and remaining_pence > 0
        and booking_item_refund is None
    )

    return render(request, "dashboard/booking_detail.html", {
        "booking": booking,
        "section": "bookings",
        "reminders": reminders,
        "last_reminder": last_reminder,
        "reminder_confirm": reminder_confirm,
        "order": order,
        "booking_order_item": booking_order_item,
        "booking_item_refund": booking_item_refund,
        "can_refund": can_refund,
        "remaining_pence": remaining_pence,
    })

@owner_required
@require_POST
def send_reminder(request, pk):
    """
    Manually send a payment-reminder email for a pending booking.

    First POST (no ``confirmed`` field): if a reminder was already sent,
    redirect back with a warning so the owner can confirm the resend.
    Second POST (``confirmed=1``): send unconditionally.
    """
    from django.contrib import messages as dj_messages
    from apps.booking.models import Booking
    from apps.payments.services.reminder import send_payment_reminder_email
    from apps.payments.models import PaymentReminder

    booking = get_object_or_404(Booking, pk=pk)

    if booking.status != Booking.STATUS_PENDING:
        dj_messages.error(request, "Only pending bookings can receive a payment reminder.")
        return redirect("dashboard:booking_detail", pk=pk)

    last = booking.payment_reminders.order_by("-sent_at").first()
    confirmed = request.POST.get("confirmed") == "1"

    if last and not confirmed:
        # Store a flag in session so the template shows the confirm banner.
        request.session[f"reminder_confirm_{pk}"] = True
        return redirect("dashboard:booking_detail", pk=pk)

    result = send_payment_reminder_email(
        booking,
        source=PaymentReminder.SOURCE_MANUAL,
        sent_by=request.user,
    )

    if result:
        dj_messages.success(request, f"Reminder sent to {booking.client_email}.")
    else:
        dj_messages.error(
            request,
            "Could not send reminder — this booking has no associated order yet. "
            "Was it created manually without going through checkout?"
        )

    # Clear the confirm flag if it was set.
    request.session.pop(f"reminder_confirm_{pk}", None)
    return redirect("dashboard:booking_detail", pk=pk)


@owner_required
@require_POST
def booking_issue_refund(request, pk):
    """
    Shortcut: issue a refund for the single booking item from the booking detail page.
    Redirects to booking_detail on completion.
    POSTs to order_refund internally so all refund logic stays in one place.
    """
    from django.contrib import messages as dj_messages
    from apps.booking.models import Booking
    from apps.payments.interfaces import RefundError
    from apps.payments.models import OrderItem
    from apps.payments.services.refund import issue_refund as _issue_refund

    booking = get_object_or_404(Booking, pk=pk)
    order_item = booking.order_items.select_related("order").first()

    if not order_item:
        dj_messages.error(request, "This booking has no associated order — nothing to refund.")
        return redirect("dashboard:booking_detail", pk=pk)

    order = order_item.order
    notes = request.POST.get("notes", "").strip()

    try:
        refund = _issue_refund(
            order,
            amount_pence=order_item.line_total_pence,
            order_item=order_item,
            initiated_by=request.user,
            notes=notes,
        )
        dj_messages.success(
            request,
            f"Refund of {refund.amount_display} processed. "
            f"Stripe ID: {refund.stripe_refund_id}",
        )
    except (ValueError, RefundError) as exc:
        dj_messages.error(request, str(exc))

    return redirect("dashboard:booking_detail", pk=pk)


@owner_required
@require_POST
def booking_delete(request, pk):
    """Hard-delete a booking."""
    from apps.booking.models import Booking
    from apps.booking.services import google_calendar
    booking = get_object_or_404(Booking, pk=pk)
    google_calendar.delete_event(booking)
    booking.delete()
    return redirect("dashboard:bookings")


@owner_required
def booking_create(request):
    """Create a new booking manually."""
    from apps.booking.models import Booking
    from .forms import BookingForm
    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("dashboard:bookings")
    else:
        form = BookingForm()
    return render(request, "dashboard/booking_form.html", {
        "form": form,
        "section": "bookings",
        "action": "Create"
    })

@owner_required
def booking_edit(request, pk):
    """Edit an existing booking fully."""
    from apps.booking.models import Booking
    from .forms import BookingForm
    booking = get_object_or_404(Booking, pk=pk)
    if request.method == "POST":
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            return redirect("dashboard:booking_detail", pk=pk)
    else:
        form = BookingForm(instance=booking)
    return render(request, "dashboard/booking_form.html", {
        "form": form,
        "booking": booking,
        "section": "bookings",
        "action": "Edit"
    })


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@owner_required
def order_detail(request, pk):
    """Order detail — shows line items, refund history, and refund controls."""
    from apps.payments.models import Order

    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__booking__session_type",
            "items__booking__location",
            "items__product",
            "items__refunds",
            "refunds__initiated_by",
            "refunds__order_item",
        ),
        pk=pk,
    )

    # Annotate each item with its total already-refunded amount.
    for item in order.items.all():
        item.refunded_pence = sum(
            r.amount_pence for r in item.refunds.all() if r.status == "succeeded"
        )
        item.refundable_pence = max(0, item.line_total_pence - item.refunded_pence)

    return render(request, "dashboard/order_detail.html", {
        "order": order,
        "section": "orders",
        "refunds": order.refunds.order_by("-created_at"),
    })


@owner_required
@require_POST
def order_refund(request, pk):
    """
    Issue a refund against an order.

    Three modes, distinguished by POST fields:
      order_item_pk  → refund that specific line item (full item price)
      amount_pence   → custom-amount refund (no item attachment)
      refund_all=1   → refund the full remaining balance
    """
    from django.contrib import messages as dj_messages
    from apps.payments.interfaces import RefundError
    from apps.payments.models import Order, OrderItem
    from apps.payments.services.refund import issue_refund as _issue_refund

    order = get_object_or_404(Order, pk=pk)
    notes = request.POST.get("notes", "").strip()

    order_item = None
    amount_pence = None

    order_item_pk = request.POST.get("order_item_pk", "").strip()
    custom_amount = request.POST.get("amount_pence", "").strip()
    refund_all    = request.POST.get("refund_all") == "1"

    if order_item_pk:
        order_item = get_object_or_404(OrderItem, pk=order_item_pk, order=order)
        # Refund the remaining un-refunded portion of this item.
        item_refunded = sum(
            r.amount_pence
            for r in order_item.refunds.filter(status="succeeded")
        )
        amount_pence = max(0, order_item.line_total_pence - item_refunded)
        if amount_pence == 0:
            dj_messages.error(request, f"'{order_item.label}' has already been fully refunded.")
            return redirect("dashboard:order_detail", pk=pk)
    elif refund_all:
        amount_pence = order.remaining_refundable_pence
    elif custom_amount:
        try:
            # Accept both pence (integer) and pounds (decimal like "12.50").
            # Use Decimal — float arithmetic loses precision on amounts like
            # £12.57 (float("12.57") * 100 = 1256.9999...).
            # to_integral_value(ROUND_HALF_UP) avoids int() truncation for
            # sub-penny inputs (e.g. "12.576" → 1258, not 1257).
            from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
            raw = custom_amount.replace("£", "").strip()
            if "." in raw:
                amount_pence = int(
                    (Decimal(raw) * 100).to_integral_value(rounding=ROUND_HALF_UP)
                )
            else:
                amount_pence = int(raw)
        except (InvalidOperation, ValueError, TypeError):
            dj_messages.error(request, "Invalid refund amount.")
            return redirect("dashboard:order_detail", pk=pk)
    else:
        dj_messages.error(request, "No refund amount specified.")
        return redirect("dashboard:order_detail", pk=pk)

    try:
        refund = _issue_refund(
            order,
            amount_pence=amount_pence,
            order_item=order_item,
            initiated_by=request.user,
            notes=notes,
        )
        dj_messages.success(
            request,
            f"Refund of {refund.amount_display} processed. "
            f"Stripe ID: {refund.stripe_refund_id}",
        )
    except (ValueError, RefundError) as exc:
        dj_messages.error(request, str(exc))

    return redirect("dashboard:order_detail", pk=pk)


@owner_required
@require_POST
def order_item_ship(request, order_pk, item_pk):
    """Mark a product order item as shipped (toggles shipped flag)."""
    from django.contrib import messages as dj_messages
    from apps.payments.models import OrderItem

    item = get_object_or_404(OrderItem, pk=item_pk, order_id=order_pk, item_type="product")
    item.shipped = not item.shipped
    item.save(update_fields=["shipped"])
    state = "shipped" if item.shipped else "unshipped"
    dj_messages.success(request, f"'{item.label}' marked as {state}.")
    return redirect("dashboard:order_detail", pk=order_pk)


@owner_required
@require_POST
def order_delete(request, pk):
    """Hard-delete an order and its line items."""
    from apps.payments.models import Order
    order = get_object_or_404(Order, pk=pk)
    order.delete()
    return redirect("dashboard:orders")


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


def _resolve_category(post_data):
    """
    Resolve category_name text input → ProductCategory pk.
    Matches case-insensitively; creates a new category if no match found.
    """
    from apps.shop.models import ProductCategory
    from django.utils.text import slugify

    data = post_data.copy()
    name = data.get("category_name", "").strip()
    if name:
        cat = ProductCategory.objects.filter(name__iexact=name).first()
        if not cat:
            base = slugify(name) or "category"
            slug, n = base, 1
            while ProductCategory.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            cat = ProductCategory.objects.create(name=name, slug=slug)
        data["category"] = str(cat.pk)
    return data


def _product_form_context(extra=None):
    from apps.shop.models import ProductCategory
    ctx = {"all_categories": ProductCategory.objects.order_by("name")}
    if extra:
        ctx.update(extra)
    return ctx


@owner_required
def product_create(request):
    from .forms import ProductForm
    if request.method == "POST":
        form = ProductForm(_resolve_category(request.POST), request.FILES)
        if form.is_valid():
            form.save()
            return redirect("dashboard:products")
    else:
        form = ProductForm()
    return render(request, "dashboard/products/form.html", _product_form_context({
        "form": form,
        "section": "products",
        "action": "Create",
    }))


@owner_required
def product_edit(request, pk):
    from apps.shop.models import Product
    from .forms import ProductForm
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(_resolve_category(request.POST), request.FILES, instance=product)
        if form.is_valid():
            form.save()
            return redirect("dashboard:products")
    else:
        form = ProductForm(instance=product)
    return render(request, "dashboard/products/form.html", _product_form_context({
        "form": form,
        "product": product,
        "current_category_name": product.category.name if product.category_id else "",
        "section": "products",
        "action": "Edit",
    }))


@owner_required
@require_POST
def product_delete(request, pk):
    """Delete a product."""
    from apps.shop.models import Product
    product = get_object_or_404(Product, pk=pk)
    product.delete()
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
    from apps.pages.models import SiteConfig, HeroSection, ApproachSection
    from apps.booking.models import BookingSettings, GoogleCalendarConfig
    from apps.shop.models import ShopSettings

    site = SiteConfig.load()
    hero = HeroSection.load()
    approach = ApproachSection.load()
    booking_settings = BookingSettings.load()
    shop_settings = ShopSettings.load()
    gcal_config = GoogleCalendarConfig.load()

    # Build the formset factory once — used in both the POST (reminders section)
    # and GET (render) paths to avoid duplicating the factory definition.
    from apps.payments.models import PaymentReminderRule
    from django.forms import modelformset_factory
    ReminderFormSet = modelformset_factory(
        PaymentReminderRule,
        fields=["delay_hours", "delay_anchor", "is_active"],
        can_delete=True,
        extra=0,
    )

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
            if "currency" in request.POST:
                currency = request.POST["currency"]
                if currency in ("GBP", "EUR", "USD"):
                    site.currency = currency
            site.save()

        elif section == "hero":
            for field in ["headline", "subheadline",
                          "cta_primary_text", "cta_secondary_text", "strip_items"]:
                if field in request.POST:
                    setattr(hero, field, request.POST[field])
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

        elif section == "approach":
            for field in ["kicker", "headline", "headline_accent", "body"]:
                if field in request.POST:
                    setattr(approach, field, request.POST[field])
            approach.save()

        elif section == "shop":
            for field in ["kicker", "heading", "heading_emphasis",
                          "subheading", "free_shipping_note"]:
                if field in request.POST:
                    setattr(shop_settings, field, request.POST[field])
            # £ decimal inputs → pence integers.  ROUND_HALF_UP avoids int()
            # truncation for sub-penny inputs.
            from decimal import Decimal as _D, ROUND_HALF_UP, InvalidOperation
            for input_name, model_attr in [
                ("free_shipping_threshold", "free_shipping_threshold_pence"),
                ("shipping_rate", "shipping_rate_pence"),
            ]:
                raw = request.POST.get(input_name, "").strip()
                if raw:
                    try:
                        setattr(
                            shop_settings,
                            model_attr,
                            int((_D(raw) * 100).to_integral_value(rounding=ROUND_HALF_UP)),
                        )
                    except (ValueError, InvalidOperation):
                        pass
            shop_settings.save()

        elif section == "gcal":
            for field in ["client_id", "client_secret", "calendar_id"]:
                val = request.POST.get(field, "").strip()
                if val:
                    setattr(gcal_config, field, val)
            gcal_config.sync_deletions_from_calendar = (
                request.POST.get("sync_deletions_from_calendar") == "on"
            )
            gcal_config.save(update_fields=[
                "client_id", "client_secret", "calendar_id",
                "sync_deletions_from_calendar",
            ])
            return redirect("/dashboard/settings/#gcal")

        elif section == "reminders":
            formset = ReminderFormSet(request.POST, prefix="reminder_rules",
                                      queryset=PaymentReminderRule.objects.all())
            if formset.is_valid():
                formset.save()
            return redirect("/dashboard/settings/#reminders")

        return redirect("dashboard:settings")

    reminder_formset = ReminderFormSet(
        prefix="reminder_rules",
        queryset=PaymentReminderRule.objects.all(),
    )

    return render(request, "dashboard/settings.html", {
        "site": site,
        "hero": hero,
        "approach": approach,
        "booking_settings": booking_settings,
        "shop_settings": shop_settings,
        "gcal_config": gcal_config,
        "reminder_formset": reminder_formset,
        "section": "settings",
    })


# ---------------------------------------------------------------------------
# Account (current user's own settings — passkeys, etc.)
# ---------------------------------------------------------------------------

@owner_required
def account_view(request):
    """Personal account settings for the logged-in staff/owner."""
    return render(request, "dashboard/account.html", {"section": "account"})


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


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@owner_required
def location_list(request):
    """List all locations."""
    from apps.booking.models import Location
    locations = Location.objects.all()
    return render(request, "dashboard/locations/list.html", {
        "locations": locations, 
        "section": "locations"
    })

@owner_required
def location_create(request):
    """Create a new location."""
    from .forms import LocationForm
    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("dashboard:location_list")
    else:
        form = LocationForm()
    return render(request, "dashboard/locations/form.html", {
        "form": form, 
        "section": "locations", 
        "action": "Create"
    })

@owner_required
def location_edit(request, pk):
    """Edit an existing location."""
    from apps.booking.models import Location
    from .forms import LocationForm
    location = get_object_or_404(Location, pk=pk)
    if request.method == "POST":
        form = LocationForm(request.POST, instance=location)
        if form.is_valid():
            form.save()
            return redirect("dashboard:location_list")
    else:
        form = LocationForm(instance=location)
    return render(request, "dashboard/locations/form.html", {
        "form": form, 
        "location": location, 
        "section": "locations", 
        "action": "Edit"
    })

@owner_required
@require_POST
def location_delete(request, pk):
    """Delete a location."""
    from apps.booking.models import Location
    location = get_object_or_404(Location, pk=pk)
    location.delete()
    return redirect("dashboard:location_list")


# ---------------------------------------------------------------------------
# Session Types
# ---------------------------------------------------------------------------

@owner_required
def sessiontype_list(request):
    """List all session types."""
    from apps.booking.models import SessionType
    session_types = SessionType.objects.all()
    return render(request, "dashboard/sessiontypes/list.html", {
        "session_types": session_types, 
        "section": "sessiontypes"
    })

@owner_required
def sessiontype_create(request):
    """Create a new session type."""
    from .forms import SessionTypeForm
    if request.method == "POST":
        form = SessionTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("dashboard:sessiontype_list")
    else:
        form = SessionTypeForm()
    return render(request, "dashboard/sessiontypes/form.html", {
        "form": form, 
        "section": "sessiontypes", 
        "action": "Create"
    })

@owner_required
def sessiontype_edit(request, pk):
    """Edit an existing session type."""
    from apps.booking.models import SessionType, Location, SessionPricing
    from .forms import SessionTypeForm
    session_type = get_object_or_404(SessionType, pk=pk)
    if request.method == "POST":
        form = SessionTypeForm(request.POST, instance=session_type)
        if form.is_valid():
            form.save()
            # Also update pricing
            locations = Location.objects.filter(is_active=True)
            for location in locations:
                price_str = request.POST.get(f"price_{location.pk}", "").strip()
                if price_str:
                    try:
                        price_pence = round(float(price_str) * 100)
                        SessionPricing.objects.update_or_create(
                            session_type=session_type,
                            location=location,
                            defaults={"price_pence": price_pence},
                        )
                    except (ValueError, TypeError):
                        pass
                else:
                    SessionPricing.objects.filter(
                        session_type=session_type, location=location
                    ).delete()
            return redirect("dashboard:sessiontype_list")
    else:
        form = SessionTypeForm(instance=session_type)

    locations = Location.objects.filter(is_active=True).order_by("order", "name")
    pricing_map = {
        p.location_id: p.price_pence
        for p in SessionPricing.objects.filter(session_type=session_type)
    }
    locations_with_pricing = [
        {"location": loc, "price_pounds": f"{pricing_map[loc.pk] / 100:.2f}" if loc.pk in pricing_map else ""}
        for loc in locations
    ]

    return render(request, "dashboard/sessiontypes/form.html", {
        "form": form,
        "session_type": session_type,
        "section": "sessiontypes",
        "action": "Edit",
        "locations_with_pricing": locations_with_pricing,
    })

@owner_required
@require_POST
def sessiontype_delete(request, pk):
    """Delete a session type."""
    from apps.booking.models import SessionType
    session_type = get_object_or_404(SessionType, pk=pk)
    session_type.delete()
    return redirect("dashboard:sessiontype_list")


@owner_required
@require_POST
def sessiontype_pricing_update(request, pk):
    """Upsert/remove pricing entries for all active locations."""
    from apps.booking.models import SessionType, Location, SessionPricing
    session_type = get_object_or_404(SessionType, pk=pk)
    locations = Location.objects.filter(is_active=True)
    for location in locations:
        price_str = request.POST.get(f"price_{location.pk}", "").strip()
        if price_str:
            try:
                price_pence = round(float(price_str) * 100)
                SessionPricing.objects.update_or_create(
                    session_type=session_type,
                    location=location,
                    defaults={"price_pence": price_pence},
                )
            except (ValueError, TypeError):
                pass
        else:
            SessionPricing.objects.filter(
                session_type=session_type, location=location
            ).delete()
    return redirect("dashboard:sessiontype_edit", pk=pk)


# ---------------------------------------------------------------------------
# Recurring Schedules
# ---------------------------------------------------------------------------

@owner_required
def schedule_list(request):
    """List all recurring schedules."""
    from apps.booking.models import RecurringSchedule
    schedules = RecurringSchedule.objects.select_related("session_type", "location").all()
    return render(request, "dashboard/schedules/list.html", {
        "schedules": schedules, 
        "section": "schedules"
    })

@owner_required
def schedule_create(request):
    """Create a new recurring schedule."""
    from .forms import RecurringScheduleForm
    if request.method == "POST":
        form = RecurringScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("dashboard:schedule_list")
    else:
        form = RecurringScheduleForm()
    return render(request, "dashboard/schedules/form.html", {
        "form": form, 
        "section": "schedules", 
        "action": "Create"
    })

@owner_required
def schedule_edit(request, pk):
    """Edit an existing recurring schedule."""
    from apps.booking.models import RecurringSchedule
    from .forms import RecurringScheduleForm
    schedule = get_object_or_404(RecurringSchedule, pk=pk)
    if request.method == "POST":
        form = RecurringScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            return redirect("dashboard:schedule_list")
    else:
        form = RecurringScheduleForm(instance=schedule)
    return render(request, "dashboard/schedules/form.html", {
        "form": form, 
        "schedule": schedule, 
        "section": "schedules", 
        "action": "Edit"
    })

@owner_required
@require_POST
def schedule_delete(request, pk):
    """Delete a recurring schedule."""
    from apps.booking.models import RecurringSchedule
    schedule = get_object_or_404(RecurringSchedule, pk=pk)
    schedule.delete()
    return redirect("dashboard:schedule_list")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

from .forms import UserForm

@owner_required
def user_list(request):
    """List all users (staff, clients, etc). ADMIN_EMAIL is excluded — stays invisible."""
    from django.conf import settings
    admin_email = getattr(settings, "ADMIN_EMAIL", "")
    users = User.objects.exclude(email=admin_email) if admin_email else User.objects.all()
    return render(request, "dashboard/users/list.html", {
        "users": users, 
        "section": "users"
    })

@owner_required
def user_create(request):
    """Create a new user."""
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Assign a random unuseable password so the user can be saved
            user.set_unusable_password()
            user.save()
            return redirect("dashboard:user_list")
    else:
        form = UserForm()
    return render(request, "dashboard/users/form.html", {
        "form": form, 
        "section": "users", 
        "action": "Create"
    })

@owner_required
def user_edit(request, pk):
    """Edit an existing user."""
    user_obj = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            return redirect("dashboard:user_list")
    else:
        form = UserForm(instance=user_obj)
    return render(request, "dashboard/users/form.html", {
        "form": form, 
        "user_obj": user_obj, 
        "section": "users", 
        "action": "Edit"
    })

@owner_required
@require_POST
def user_delete(request, pk):
    """Delete a user."""
    user_obj = get_object_or_404(User, pk=pk)
    # Don't delete the current logged in user
    if user_obj.pk != request.user.pk:
        user_obj.delete()
    return redirect("dashboard:user_list")


# ---------------------------------------------------------------------------
# Google Calendar OAuth
# ---------------------------------------------------------------------------

@owner_required
def gcal_connect(request):
    """Redirect owner to Google's consent page."""
    from apps.booking.services.google_calendar import get_auth_url
    from apps.booking.models import GoogleCalendarConfig

    config = GoogleCalendarConfig.load()
    if not config.client_id or not config.client_secret:
        return redirect("dashboard:settings")

    redirect_uri = request.build_absolute_uri("/dashboard/google-calendar/callback/")
    auth_url, code_verifier = get_auth_url(redirect_uri)
    # Stash the PKCE verifier in the session — needed in the callback
    request.session["gcal_code_verifier"] = code_verifier
    return redirect(auth_url)


@owner_required
def gcal_callback(request):
    """Handle Google's OAuth2 redirect; exchange code for tokens."""
    from apps.booking.services.google_calendar import handle_oauth_callback

    code = request.GET.get("code")
    if not code:
        return redirect("dashboard:settings")

    redirect_uri = request.build_absolute_uri("/dashboard/google-calendar/callback/")
    code_verifier = request.session.pop("gcal_code_verifier", None)
    try:
        handle_oauth_callback(code, redirect_uri, code_verifier=code_verifier)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Google Calendar callback failed: %s", exc)

    return redirect("/dashboard/settings/#gcal")


@owner_required
@require_POST
def gcal_disconnect(request):
    """Wipe stored tokens."""
    from apps.booking.services.google_calendar import disconnect
    disconnect()
    return redirect("/dashboard/settings/#gcal")


@owner_required
@require_POST
def gcal_sync(request):
    """Manually trigger a Google Calendar → DB sync."""
    from apps.booking.services.google_calendar import sync_from_calendar
    synced, cancelled = sync_from_calendar()
    params = f"?sync_synced={synced}&sync_cancelled={cancelled}"
    return redirect(f"/dashboard/settings/{params}#gcal")
