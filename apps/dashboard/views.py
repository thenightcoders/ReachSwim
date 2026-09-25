"""
Owner dashboard views — the bespoke screens.

Straightforward model sections (pools, session types, timetable, packages,
vouchers, package credits, categories, website content) are declared in
registry.py on top of the generic Crud engine. Everything here is gated
behind @owner_required.
"""
import csv
import datetime
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, ProtectedError, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import owner_required
from apps.accounts.models import User

logger = logging.getLogger(__name__)

PER_PAGE = 50


def _paginate(request, qs, per_page=PER_PAGE):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _next_or(request, fallback):
    nxt = request.POST.get("next", "")
    return nxt if nxt.startswith("/dashboard/") else fallback


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def _pool_timeline(bookings, now):
    """
    Lay out today's bookings as swimmers in lanes (one lane per pool).
    Positions are percentages across an hour range that always covers 07–21
    and stretches to fit earlier/later sessions.
    """
    first = min([b.start_time.hour for b in bookings] + [7])
    last = max([b.end_time.hour + (1 if b.end_time.minute else 0) for b in bookings] + [21])
    span = (last - first) * 60

    def pct(t):
        return round(((t.hour - first) * 60 + t.minute) / span * 100, 3)

    lanes = {}
    for b in bookings:
        lane = lanes.setdefault(b.location_id, {"name": b.location.name, "swims": {}})
        key = (b.session_type_id, b.start_time, b.end_time)
        swim = lane["swims"].get(key)
        if swim is None:
            swim = lane["swims"][key] = {
                "left": pct(b.start_time),
                "width": max(pct(b.end_time) - pct(b.start_time), 2),
                "start": b.start_time,
                "end": b.end_time,
                "session": b.session_type.name,
                "names": [],
                "status": b.status,
                "url": reverse("dashboard:booking_detail", args=[b.pk]),
            }
        swim["names"].append(b.client_name)
        if b.status == "pending":
            swim["status"] = "pending"

    now_pct = None
    if first * 60 <= now.hour * 60 + now.minute <= last * 60:
        now_pct = pct(now.time())

    return {
        "hours": [f"{h:02d}" for h in range(first, last)],
        "hour_count": last - first,
        "lanes": [{"name": l["name"], "swims": list(l["swims"].values())} for l in lanes.values()],
        "now_pct": now_pct,
    }


@owner_required
def home(request):
    from apps.booking.models import Booking
    from apps.legal.models import ContactMessage
    from apps.payments.models import Order, PackagePurchase
    from apps.shop.models import Product

    now = timezone.localtime()
    today = now.date()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    today_bookings = list(
        Booking.objects.filter(date=today, status__in=["pending", "confirmed", "completed"])
        .select_related("session_type", "location").order_by("start_time")
    )
    upcoming_bookings = (
        Booking.objects.filter(date__gt=today, status__in=["pending", "confirmed"])
        .select_related("session_type", "location").order_by("date", "start_time")[:8]
    )
    paid = Order.objects.filter(status="paid")

    return render(request, "dashboard/home.html", {
        "section": "home",
        "now": now,
        "timeline": _pool_timeline(today_bookings, now),
        "today_bookings": today_bookings,
        "today_count": sum(1 for b in today_bookings if b.status == "confirmed"),
        "upcoming_bookings": upcoming_bookings,
        "week_revenue": paid.filter(created_at__date__gte=week_start).aggregate(t=Sum("total_pence"))["t"] or 0,
        "month_revenue": paid.filter(created_at__date__gte=month_start).aggregate(t=Sum("total_pence"))["t"] or 0,
        "pending_orders": Order.objects.filter(status="pending").count(),
        "pending_bookings": Booking.objects.filter(status="pending", date__gte=today).count(),
        # Unique client emails across all bookings — includes guest checkouts.
        "total_clients": Booking.objects.values("client_email").distinct().count(),
        "unread_messages": ContactMessage.objects.filter(is_read=False).count(),
        "recent_orders": Order.objects.order_by("-created_at")[:5],
        "recent_messages": ContactMessage.objects.order_by("-created_at")[:4],
        "low_stock": Product.objects.filter(is_active=True, stock__lte=3).order_by("stock", "name")[:5],
        "unshipped": Order.objects.filter(status="paid", items__item_type="product", items__shipped=False).distinct().count(),
        "active_packages": PackagePurchase.objects.filter(is_active=True, expires_at__gte=now).count(),
    })


# ---------------------------------------------------------------------------
# Global search (command palette)
# ---------------------------------------------------------------------------

@owner_required
def search(request):
    from apps.booking.models import Booking
    from apps.payments.models import Order, Voucher
    from apps.shop.models import Product

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"groups": []})

    people = User.objects.filter(Q(full_name__icontains=q) | Q(email__icontains=q))[:5]
    bookings = (Booking.objects.filter(Q(client_name__icontains=q) | Q(client_email__icontains=q) | Q(reference__istartswith=q))
                .exclude(status="draft").select_related("session_type").order_by("-date")[:6])
    orders = Order.objects.filter(
        Q(client_name__icontains=q) | Q(client_email__icontains=q) | Q(reference__istartswith=q) | Q(voucher_code__iexact=q)
    ).order_by("-created_at")[:5]
    vouchers = Voucher.objects.filter(code__icontains=q, package_purchase__isnull=True)[:4]
    products = Product.objects.filter(Q(name__icontains=q) | Q(color__icontains=q))[:4]

    groups = [
        {"name": "People", "results": [
            {"label": u.full_name or u.email, "sub": u.email, "url": reverse("dashboard:user_detail", args=[u.pk])} for u in people]},
        {"name": "Bookings", "results": [
            {"label": f"{b.client_name}, {b.session_type.name}", "sub": f"{b.date:%a %-d %b} at {b.start_time:%H:%M}",
             "url": reverse("dashboard:booking_detail", args=[b.pk])} for b in bookings]},
        {"name": "Orders", "results": [
            {"label": f"Order {o.order_number}", "sub": f"{o.client_name}, {o.get_status_display().lower()}",
             "url": reverse("dashboard:order_detail", args=[o.pk])} for o in orders]},
        {"name": "Vouchers", "results": [
            {"label": v.code, "sub": "Voucher", "url": reverse("dashboard:voucher_edit", args=[v.pk])} for v in vouchers]},
        {"name": "Products", "results": [
            {"label": str(p), "sub": f"{p.stock} in stock", "url": reverse("dashboard:product_edit", args=[p.pk])} for p in products]},
    ]
    return JsonResponse({"groups": [g for g in groups if g["results"]]})


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

BOOKING_STATUSES = [("pending", "Pending"), ("confirmed", "Confirmed"), ("completed", "Completed"),
                    ("cancelled", "Cancelled"), ("draft", "Unfinished")]


def _filtered_bookings(request):
    from apps.booking.models import Booking

    qs = Booking.with_spots_taken().select_related("session_type", "location")
    g = request.GET
    status = g.get("status", "")
    when = g.get("when", "")
    today = timezone.localdate()

    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status=Booking.STATUS_DRAFT)
    if when == "upcoming":
        qs = qs.filter(date__gte=today)
    elif when == "today":
        qs = qs.filter(date=today)
    elif when == "past":
        qs = qs.filter(date__lt=today)
    if g.get("from"):
        qs = qs.filter(date__gte=g["from"])
    if g.get("to"):
        qs = qs.filter(date__lte=g["to"])
    if g.get("location"):
        qs = qs.filter(location_id=g["location"])
    if g.get("session_type"):
        qs = qs.filter(session_type_id=g["session_type"])
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(client_name__icontains=q) | Q(client_email__icontains=q) | Q(reference__istartswith=q))

    if when == "upcoming":
        return qs.order_by("date", "start_time")
    return qs.order_by("-date", "-start_time")


@owner_required
def bookings(request):
    from apps.booking.models import Booking, Location, SessionType

    qs = _filtered_bookings(request)

    if request.GET.get("export") == "csv":
        return _csv_response(
            f"bookings-{timezone.localdate():%Y-%m-%d}.csv",
            ["Reference", "Date", "Start", "End", "Session", "Pool", "Client", "Email", "Phone", "Status", "Amount (£)", "Notes"],
            ([str(b.reference), b.date, b.start_time.strftime("%H:%M"), b.end_time.strftime("%H:%M"), b.session_type.name,
              b.location.name, b.client_name, b.client_email, b.client_phone, b.get_status_display(),
              f"{b.amount_pence / 100:.2f}", b.notes] for b in qs.iterator()),
        )

    counts = dict(Booking.objects.values_list("status").annotate(n=Count("pk")))
    filter_keys = ("status", "when", "from", "to", "q", "location", "session_type")
    return render(request, "dashboard/bookings.html", {
        "section": "bookings",
        "page_obj": _paginate(request, qs),
        "statuses": [(k, l, counts.get(k, 0)) for k, l in BOOKING_STATUSES],
        "all_count": sum(v for k, v in counts.items() if k != "draft"),
        "locations": Location.objects.order_by("order", "name"),
        "session_types": SessionType.objects.order_by("order", "name"),
        "f": {k: request.GET.get(k, "") for k in filter_keys},
        "is_filtered": any(request.GET.get(k) for k in filter_keys),
    })


@owner_required
@require_POST
def bookings_bulk(request):
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking, complete_booking, confirm_booking
    from apps.booking.services.email import send_booking_confirmation
    from apps.booking.services import google_calendar

    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    qs = Booking.objects.filter(pk__in=ids)
    back = _next_or(request, reverse("dashboard:bookings"))
    if not ids:
        messages.warning(request, "Select at least one booking first.")
        return redirect(back)

    if action == "confirm":
        done = [confirm_booking(b) for b in qs.filter(status=Booking.STATUS_PENDING)]
        msg = f"{len(done)} booking(s) confirmed. Clients have been emailed."
    elif action == "complete":
        done = [complete_booking(b) for b in qs.filter(status=Booking.STATUS_CONFIRMED)]
        msg = f"{len(done)} booking(s) marked as completed."
    elif action == "cancel":
        reason = request.POST.get("reason", "").strip() or "Cancelled by coach."
        done = [cancel_booking(b, reason=reason) for b in qs.exclude(status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED])]
        msg = f"{len(done)} booking(s) cancelled."
    elif action == "resend":
        sent = sum(1 for b in qs.filter(status=Booking.STATUS_CONFIRMED) if send_booking_confirmation(b))
        msg = f"Confirmation emails sent for {sent} booking(s)."
    elif action == "delete":
        n = 0
        for b in qs:
            google_calendar.delete_event(b)
            b.delete()
            n += 1
        msg = f"{n} booking(s) deleted."
    else:
        messages.error(request, "Choose an action to apply.")
        return redirect(back)

    messages.success(request, msg)
    return redirect(back)


@owner_required
def booking_detail(request, pk):
    from apps.booking.models import Booking
    from apps.booking.services.booking import cancel_booking, complete_booking, confirm_booking
    from apps.booking.services.email import send_booking_confirmation

    booking = get_object_or_404(Booking.objects.select_related("session_type", "location", "user"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm" and booking.status == Booking.STATUS_PENDING:
            confirm_booking(booking)
            messages.success(request, "Booking confirmed. The client has been emailed.")
        elif action == "cancel" and booking.status in (Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED):
            cancel_booking(booking, reason=request.POST.get("reason", ""))
            messages.success(request, "Booking cancelled.")
        elif action == "complete" and booking.status == Booking.STATUS_CONFIRMED:
            complete_booking(booking)
            messages.success(request, "Booking marked as completed.")
        elif action == "resend" and booking.status == Booking.STATUS_CONFIRMED:
            if send_booking_confirmation(booking):
                messages.success(request, f"Confirmation resent to {booking.client_email}.")
            else:
                messages.error(request, "The confirmation email couldn't be sent. Check the email settings and logs.")
        elif action == "save_notes":
            booking.notes = request.POST.get("notes", "")
            booking.save(update_fields=["notes", "updated_at"])
            messages.success(request, "Notes saved.")
        return redirect("dashboard:booking_detail", pk=pk)

    reminders = booking.payment_reminders.select_related("rule", "sent_by").order_by("-sent_at")
    reminder_confirm = request.session.pop(f"reminder_confirm_{pk}", False)

    booking_order_item = booking.order_items.select_related("order").first()
    order = booking_order_item.order if booking_order_item else None
    booking_item_refund = (
        booking_order_item.refunds.filter(status="succeeded").first() if booking_order_item else None
    )
    remaining_pence = order.remaining_refundable_pence if order else 0

    same_slot = (
        Booking.objects.filter(session_type=booking.session_type, location=booking.location, date=booking.date,
                               start_time=booking.start_time)
        .exclude(pk=booking.pk).exclude(status__in=["cancelled", "draft"])
    )
    history = (
        Booking.objects.filter(client_email__iexact=booking.client_email).exclude(pk=booking.pk)
        .select_related("session_type").order_by("-date")[:6]
    )
    account = booking.user or User.objects.filter(email__iexact=booking.client_email).first()

    return render(request, "dashboard/booking_detail.html", {
        "booking": booking,
        "section": "bookings",
        "reminders": reminders,
        "last_reminder": reminders.first(),
        "reminder_confirm": reminder_confirm,
        "order": order,
        "booking_order_item": booking_order_item,
        "booking_item_refund": booking_item_refund,
        "can_refund": (order is not None and bool(order.stripe_payment_intent_id)
                       and remaining_pence > 0 and booking_item_refund is None),
        "remaining_pence": remaining_pence,
        "same_slot": same_slot,
        "history": history,
        "account": account,
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
    from apps.booking.models import Booking
    from apps.payments.models import PaymentReminder
    from apps.payments.services.reminder import send_payment_reminder_email

    booking = get_object_or_404(Booking, pk=pk)
    if booking.status != Booking.STATUS_PENDING:
        messages.error(request, "Only pending bookings can receive a payment reminder.")
        return redirect("dashboard:booking_detail", pk=pk)

    last = booking.payment_reminders.order_by("-sent_at").first()
    if last and request.POST.get("confirmed") != "1":
        request.session[f"reminder_confirm_{pk}"] = True
        return redirect("dashboard:booking_detail", pk=pk)

    result = send_payment_reminder_email(booking, source=PaymentReminder.SOURCE_MANUAL, sent_by=request.user)
    if result:
        messages.success(request, f"Reminder sent to {booking.client_email}.")
    else:
        messages.error(
            request,
            "No reminder sent: this booking has no order yet. Bookings created by hand don't have a payment link.",
        )
    request.session.pop(f"reminder_confirm_{pk}", None)
    return redirect("dashboard:booking_detail", pk=pk)


@owner_required
@require_POST
def booking_issue_refund(request, pk):
    """Refund the single booking item from the booking page. Logic lives in services.refund."""
    from apps.booking.models import Booking
    from apps.payments.interfaces import RefundError
    from apps.payments.services.refund import issue_refund as _issue_refund

    booking = get_object_or_404(Booking, pk=pk)
    order_item = booking.order_items.select_related("order").first()
    if not order_item:
        messages.error(request, "This booking has no order, so there's nothing to refund.")
        return redirect("dashboard:booking_detail", pk=pk)

    try:
        refund = _issue_refund(
            order_item.order,
            amount_pence=order_item.line_total_pence,
            order_item=order_item,
            initiated_by=request.user,
            notes=request.POST.get("notes", "").strip(),
        )
        messages.success(request, f"Refunded {refund.amount_display}. Stripe ID: {refund.stripe_refund_id}")
    except (ValueError, RefundError) as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:booking_detail", pk=pk)


@owner_required
@require_POST
def booking_delete(request, pk):
    from apps.booking.models import Booking
    from apps.booking.services import google_calendar

    booking = get_object_or_404(Booking, pk=pk)
    google_calendar.delete_event(booking)
    booking.delete()
    messages.success(request, f"Booking #{pk} deleted.")
    return redirect("dashboard:bookings")


def _booking_form_page(request, booking=None):
    from .forms import BookingForm

    initial = {}
    if booking is None:
        for key in ("date", "start_time", "end_time", "session_type", "location", "client_name", "client_email"):
            if request.GET.get(key):
                initial[key] = request.GET[key]
        if "user" in request.GET:
            person = User.objects.filter(pk=request.GET["user"]).first()
            if person:
                initial.update(user=person.pk, client_name=person.full_name, client_email=person.email,
                               client_phone=person.phone)

    form = BookingForm(request.POST or None, instance=booking, initial=initial)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, "Booking saved." if booking else "Booking added.")
        return redirect("dashboard:booking_detail", pk=saved.pk)

    return render(request, "dashboard/booking_form.html", {
        "form": form, "booking": booking, "section": "bookings",
    })


@owner_required
def booking_create(request):
    return _booking_form_page(request)


@owner_required
def booking_edit(request, pk):
    from apps.booking.models import Booking
    return _booking_form_page(request, get_object_or_404(Booking, pk=pk))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _filtered_orders(request):
    from apps.payments.models import Order

    qs = Order.objects.prefetch_related("items").order_by("-created_at")
    g = request.GET
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("from"):
        qs = qs.filter(created_at__date__gte=g["from"])
    if g.get("to"):
        qs = qs.filter(created_at__date__lte=g["to"])
    if g.get("kind") in ("booking", "product", "package"):
        qs = qs.filter(items__item_type=g["kind"]).distinct()
    if g.get("unshipped"):
        qs = qs.filter(status="paid", items__item_type="product", items__shipped=False).distinct()
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(client_name__icontains=q) | Q(client_email__icontains=q)
                       | Q(reference__istartswith=q) | Q(voucher_code__iexact=q))
    return qs


@owner_required
def orders(request):
    from apps.payments.models import Order

    qs = _filtered_orders(request)
    if request.GET.get("export") == "csv":
        return _csv_response(
            f"orders-{timezone.localdate():%Y-%m-%d}.csv",
            ["Order", "Placed", "Client", "Email", "Items", "Subtotal (£)", "Discount (£)", "Total (£)", "Voucher", "Status"],
            ([o.order_number, timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"), o.client_name, o.client_email,
              "; ".join(i.label for i in o.items.all()), f"{o.subtotal_pence / 100:.2f}", f"{o.discount_pence / 100:.2f}",
              f"{o.total_pence / 100:.2f}", o.voucher_code, o.get_status_display()] for o in qs),
        )

    counts = dict(Order.objects.values_list("status").annotate(n=Count("pk")))
    keys = ("status", "q", "from", "to", "kind", "unshipped")
    return render(request, "dashboard/orders.html", {
        "section": "orders",
        "page_obj": _paginate(request, qs),
        "statuses": [(k, l, counts.get(k, 0)) for k, l in Order.STATUS_CHOICES],
        "all_count": sum(counts.values()),
        "f": {k: request.GET.get(k, "") for k in keys},
        "is_filtered": any(request.GET.get(k) for k in keys),
    })


@owner_required
@require_POST
def orders_bulk(request):
    from apps.payments.models import Order
    from apps.payments.services.checkout import cancel_pending_order

    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    back = _next_or(request, reverse("dashboard:orders"))
    qs = Order.objects.filter(pk__in=ids)
    if not ids:
        messages.warning(request, "Select at least one order first.")
    elif action == "expire":
        n = 0
        for order in qs.filter(status=Order.STATUS_PENDING):
            with transaction.atomic():
                cancel_pending_order(str(order.reference))
            n += 1
        messages.success(request, f"{n} unpaid order(s) expired and their slots released.")
    elif action == "delete":
        n = qs.count()
        qs.delete()
        messages.success(request, f"{n} order(s) deleted.")
    else:
        messages.error(request, "Choose an action to apply.")
    return redirect(back)


@owner_required
def order_detail(request, pk):
    from apps.payments.models import Order, PaymentRecord

    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__booking__session_type", "items__booking__location", "items__product",
            "items__refunds", "refunds__initiated_by", "refunds__order_item",
        ),
        pk=pk,
    )
    for item in order.items.all():
        item.refunded_pence = sum(r.amount_pence for r in item.refunds.all() if r.status == "succeeded")
        item.refundable_pence = max(0, item.line_total_pence - item.refunded_pence)

    return render(request, "dashboard/order_detail.html", {
        "order": order,
        "section": "orders",
        "refunds": order.refunds.order_by("-created_at"),
        "payments": PaymentRecord.objects.filter(Q(order=order) | Q(order_reference=str(order.reference))).order_by("-created_at"),
        "account": User.objects.filter(email__iexact=order.client_email).first(),
    })


@owner_required
@require_POST
def order_expire(request, pk):
    from apps.payments.models import Order
    from apps.payments.services.checkout import cancel_pending_order

    order = get_object_or_404(Order, pk=pk)
    if order.status != Order.STATUS_PENDING:
        messages.error(request, "Only unpaid orders can be expired.")
    else:
        with transaction.atomic():
            cancel_pending_order(str(order.reference))
        messages.success(request, "Order expired. Its bookings were cancelled and the slots released.")
    return redirect("dashboard:order_detail", pk=pk)


@owner_required
@require_POST
def order_refund(request, pk):
    """
    Issue a refund against an order.

    Three modes, distinguished by POST fields:
      order_item_pk  → refund that specific line item (remaining balance)
      amount_pence   → custom amount, in pounds ("12.50") or pence ("1250")
      refund_all=1   → refund the full remaining balance
    """
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    from apps.payments.interfaces import RefundError
    from apps.payments.models import Order, OrderItem
    from apps.payments.services.refund import issue_refund as _issue_refund

    order = get_object_or_404(Order, pk=pk)
    notes = request.POST.get("notes", "").strip()
    order_item = None
    order_item_pk = request.POST.get("order_item_pk", "").strip()
    custom_amount = request.POST.get("amount_pence", "").strip()

    if order_item_pk:
        order_item = get_object_or_404(OrderItem, pk=order_item_pk, order=order)
        item_refunded = sum(r.amount_pence for r in order_item.refunds.filter(status="succeeded"))
        amount_pence = max(0, order_item.line_total_pence - item_refunded)
        if amount_pence == 0:
            messages.error(request, f"“{order_item.label}” has already been fully refunded.")
            return redirect("dashboard:order_detail", pk=pk)
    elif request.POST.get("refund_all") == "1":
        amount_pence = order.remaining_refundable_pence
    elif custom_amount:
        try:
            # Decimal avoids float drift (12.57 * 100 = 1256.999…); HALF_UP avoids truncating sub-penny input.
            raw = custom_amount.replace("£", "").strip()
            amount_pence = (int((Decimal(raw) * 100).to_integral_value(rounding=ROUND_HALF_UP))
                            if "." in raw else int(raw))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "Enter the refund amount as a number, like 15.00.")
            return redirect("dashboard:order_detail", pk=pk)
    else:
        messages.error(request, "Enter an amount to refund.")
        return redirect("dashboard:order_detail", pk=pk)

    try:
        refund = _issue_refund(order, amount_pence=amount_pence, order_item=order_item,
                               initiated_by=request.user, notes=notes)
        messages.success(request, f"Refunded {refund.amount_display}. Stripe ID: {refund.stripe_refund_id}")
    except (ValueError, RefundError) as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:order_detail", pk=pk)


@owner_required
@require_POST
def order_item_ship(request, order_pk, item_pk):
    from apps.payments.models import OrderItem

    item = get_object_or_404(OrderItem, pk=item_pk, order_id=order_pk, item_type="product")
    item.shipped = not item.shipped
    item.save(update_fields=["shipped"])
    messages.success(request, f"“{item.label}” marked as {'shipped' if item.shipped else 'not shipped'}.")
    return redirect("dashboard:order_detail", pk=order_pk)


@owner_required
@require_POST
def order_delete(request, pk):
    from apps.payments.models import Order

    order = get_object_or_404(Order, pk=pk)
    number = order.order_number
    order.delete()
    messages.success(request, f"Order {number} deleted.")
    return redirect("dashboard:orders")


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@owner_required
def products(request):
    from apps.shop.models import Product, ProductCategory

    qs = Product.objects.select_related("category").order_by("order", "name")
    g = request.GET
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(color__icontains=q) | Q(description__icontains=q))
    if g.get("category"):
        qs = qs.filter(category_id=g["category"])
    if g.get("stock") == "low":
        qs = qs.filter(stock__gt=0, stock__lte=3)
    elif g.get("stock") == "out":
        qs = qs.filter(stock=0)
    if g.get("status") in ("1", "0"):
        qs = qs.filter(is_active=g["status"] == "1")

    keys = ("q", "category", "stock", "status")
    return render(request, "dashboard/products.html", {
        "section": "products",
        "page_obj": _paginate(request, qs),
        "categories": ProductCategory.objects.order_by("order", "name"),
        "f": {k: g.get(k, "") for k in keys},
        "is_filtered": any(g.get(k) for k in keys),
    })


@owner_required
@require_POST
def products_bulk(request):
    from apps.shop.models import Product

    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    back = _next_or(request, reverse("dashboard:products"))
    qs = Product.objects.filter(pk__in=ids)
    if not ids:
        messages.warning(request, "Select at least one product first.")
    elif action in ("show", "hide"):
        n = qs.update(is_active=action == "show")
        messages.success(request, f"{n} product(s) {'shown in' if action == 'show' else 'hidden from'} the shop.")
    elif action == "delete":
        try:
            n = qs.count()
            qs.delete()
            messages.success(request, f"{n} product(s) deleted.")
        except ProtectedError:
            messages.error(request, "Some of these products appear in orders, so they can't be deleted. Hide them instead.")
    return redirect(back)


@owner_required
@require_POST
def product_update_stock(request, pk):
    from apps.shop.models import Product

    product = get_object_or_404(Product, pk=pk)
    try:
        product.stock = max(0, int(request.POST.get("stock", 0)))
        product.save(update_fields=["stock"])
        messages.success(request, f"Stock for “{product}” set to {product.stock}.")
    except (ValueError, TypeError):
        messages.error(request, "Stock must be a whole number.")
    return redirect(_next_or(request, reverse("dashboard:products")))


@owner_required
@require_POST
def product_toggle_active(request, pk):
    from apps.shop.models import Product

    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    messages.success(request, f"“{product}” is now {'visible in' if product.is_active else 'hidden from'} the shop.")
    return redirect(_next_or(request, reverse("dashboard:products")))


def _resolve_category(post_data):
    """
    Resolve the category_name text input → ProductCategory pk.
    Matches case-insensitively; creates a new category if no match found.
    """
    from django.utils.text import slugify
    from apps.shop.models import ProductCategory

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


def _units_sold(product):
    from apps.payments.models import OrderItem
    if product is None:
        return None
    return OrderItem.objects.filter(product=product, order__status="paid").aggregate(n=Sum("quantity"))["n"] or 0


def _product_form_page(request, product=None):
    from apps.shop.models import ProductCategory
    from .forms import ProductForm

    if request.method == "POST":
        form = ProductForm(_resolve_category(request.POST), request.FILES, instance=product)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f"“{saved}” {'saved' if product else 'added'}.")
            if "_addanother" in request.POST:
                return redirect("dashboard:product_create")
            return redirect("dashboard:products")
    else:
        form = ProductForm(instance=product)

    return render(request, "dashboard/products/form.html", {
        "form": form,
        "product": product,
        "section": "products",
        "all_categories": list(ProductCategory.objects.order_by("name").values_list("name", flat=True)),
        "current_category_name": request.POST.get("category_name") if request.method == "POST"
        else (product.category.name if product and product.category_id else ""),
        "units_sold": _units_sold(product),
    })


@owner_required
def product_create(request):
    return _product_form_page(request)


@owner_required
def product_edit(request, pk):
    from apps.shop.models import Product
    return _product_form_page(request, get_object_or_404(Product, pk=pk))


@owner_required
@require_POST
def product_delete(request, pk):
    from apps.shop.models import Product

    product = get_object_or_404(Product, pk=pk)
    try:
        product.delete()
        messages.success(request, f"“{product}” deleted.")
    except ProtectedError:
        messages.error(request, f"“{product}” appears in past orders, so it can't be deleted. Hide it instead.")
        return redirect("dashboard:product_edit", pk=pk)
    return redirect("dashboard:products")


# ---------------------------------------------------------------------------
# Pricing matrix & package grants
# ---------------------------------------------------------------------------

@owner_required
def pricing(request):
    from apps.booking.models import Location, SessionPricing, SessionType
    from .registry import _save_prices

    session_types = list(SessionType.objects.order_by("order", "name"))
    locations = list(Location.objects.order_by("order", "name"))

    if request.method == "POST":
        _save_prices(request, [(f"{st.pk}_{loc.pk}", st, loc) for st in session_types for loc in locations])
        messages.success(request, "Prices saved.")
        return redirect("dashboard:pricing")

    prices = {(p.session_type_id, p.location_id): p.price_pence for p in SessionPricing.objects.all()}
    rows = [
        {"session_type": st, "cells": [{"key": f"{st.pk}_{loc.pk}", "pence": prices.get((st.pk, loc.pk))} for loc in locations]}
        for st in session_types
    ]
    return render(request, "dashboard/pricing/matrix.html", {
        "section": "pricing", "locations": locations, "rows": rows,
    })


@owner_required
def packagepurchase_grant(request):
    from apps.booking.services.package_purchase import create_purchase
    from .forms import GrantPackageForm

    initial = {}
    if request.GET.get("user"):
        person = User.objects.filter(pk=request.GET["user"]).first()
        if person:
            initial = {"client_name": person.full_name, "client_email": person.email}
    form = GrantPackageForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        email = data["client_email"].strip().lower()
        purchase = create_purchase(
            data["package"], data["client_name"], email,
            user=User.objects.filter(email__iexact=email).first(),
        )
        if data["complimentary"]:
            purchase.amount_pence = 0
            purchase.save(update_fields=["amount_pence"])
        messages.success(request, f"{data['package'].session_count} credits granted to {data['client_name']}.")
        return redirect("dashboard:packagepurchase_edit", pk=purchase.pk)

    return render(request, "dashboard/packagepurchases/grant.html", {"form": form, "section": "packagepurchases"})


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@owner_required
def messages_view(request):
    from apps.legal.models import ContactMessage

    qs = ContactMessage.objects.order_by("-created_at")
    show = request.GET.get("show", "")
    if show == "unread":
        qs = qs.filter(is_read=False)
    elif show == "read":
        qs = qs.filter(is_read=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))

    return render(request, "dashboard/messages.html", {
        "section": "messages",
        "page_obj": _paginate(request, qs),
        "show": show,
        "q": q,
        "unread_total": ContactMessage.objects.filter(is_read=False).count(),
    })


@owner_required
def message_detail(request, pk):
    from apps.legal.models import ContactMessage

    msg = get_object_or_404(ContactMessage, pk=pk)
    if not msg.is_read:
        msg.is_read = True
        msg.save(update_fields=["is_read"])
    return render(request, "dashboard/message_detail.html", {
        "section": "messages",
        "msg": msg,
        "account": User.objects.filter(email__iexact=msg.email).first(),
        "other_messages": ContactMessage.objects.filter(email__iexact=msg.email).exclude(pk=pk).order_by("-created_at")[:5],
    })


@owner_required
@require_POST
def message_mark_read(request, pk):
    """Toggle read/unread. ``state=unread`` forces unread; default marks read."""
    from apps.legal.models import ContactMessage

    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_read = request.POST.get("state") != "unread"
    msg.save(update_fields=["is_read"])
    return redirect(_next_or(request, reverse("dashboard:messages")))


@owner_required
@require_POST
def message_delete(request, pk):
    from apps.legal.models import ContactMessage

    get_object_or_404(ContactMessage, pk=pk).delete()
    messages.success(request, "Message deleted.")
    return redirect("dashboard:messages")


@owner_required
@require_POST
def messages_bulk(request):
    from apps.legal.models import ContactMessage

    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    qs = ContactMessage.objects.filter(pk__in=ids)
    if not ids:
        messages.warning(request, "Select at least one message first.")
    elif action in ("read", "unread"):
        n = qs.update(is_read=action == "read")
        messages.success(request, f"{n} message(s) marked as {action}.")
    elif action == "delete":
        n = qs.count()
        qs.delete()
        messages.success(request, f"{n} message(s) deleted.")
    return redirect(_next_or(request, reverse("dashboard:messages")))


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

def _visible_users():
    """ADMIN_EMAIL (the superuser behind /admin) stays invisible in the dashboard."""
    from django.conf import settings
    admin_email = getattr(settings, "ADMIN_EMAIL", "")
    qs = User.objects.all()
    return qs.exclude(email__iexact=admin_email) if admin_email else qs


@owner_required
def user_list(request):
    from apps.booking.models import Booking
    from django.db.models import OuterRef, Subquery

    bookings_for = Booking.objects.filter(client_email__iexact=OuterRef("email")).exclude(status__in=["draft", "cancelled"])
    qs = _visible_users().annotate(
        booking_count=Subquery(bookings_for.values("client_email").annotate(n=Count("pk")).values("n")[:1]),
        last_booking=Subquery(bookings_for.order_by("-date").values("date")[:1]),
    )
    g = request.GET
    if g.get("role"):
        qs = qs.filter(role=g["role"])
    if g.get("status") in ("1", "0"):
        qs = qs.filter(is_active=g["status"] == "1")
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    sort = g.get("o", "-date_joined")
    if sort.lstrip("-") in ("full_name", "date_joined", "last_login", "last_booking", "booking_count"):
        qs = qs.order_by(sort)

    if g.get("export") == "csv":
        return _csv_response(
            f"people-{timezone.localdate():%Y-%m-%d}.csv",
            ["Name", "Email", "Phone", "Role", "Can log in", "Joined", "Bookings", "Last booking"],
            ([u.full_name, u.email, u.phone, u.get_role_display(), "Yes" if u.is_active else "No",
              timezone.localtime(u.date_joined).strftime("%Y-%m-%d"), u.booking_count or 0, u.last_booking or ""] for u in qs),
        )

    counts = dict(_visible_users().values_list("role").annotate(n=Count("pk")))
    return render(request, "dashboard/users/list.html", {
        "section": "users",
        "page_obj": _paginate(request, qs),
        "roles": [(k, l, counts.get(k, 0)) for k, l in User.ROLE_CHOICES],
        "all_count": sum(counts.values()),
        "f": {"role": g.get("role", ""), "status": g.get("status", ""), "q": q, "o": sort},
        "is_filtered": any(g.get(k) for k in ("role", "status", "q")),
    })


@owner_required
def user_detail(request, pk):
    from apps.booking.models import Booking
    from apps.payments.models import Order, PackagePurchase
    from .forms import SetPasswordForm

    person = get_object_or_404(_visible_users(), pk=pk)
    email_q = Q(client_email__iexact=person.email)
    bookings_qs = Booking.objects.filter(email_q | Q(user=person)).exclude(status="draft").select_related("session_type", "location")
    orders_qs = Order.objects.filter(email_q)
    today = timezone.localdate()

    return render(request, "dashboard/users/detail.html", {
        "section": "users",
        "person": person,
        "upcoming": bookings_qs.filter(date__gte=today, status__in=["pending", "confirmed"]).order_by("date", "start_time"),
        "past": bookings_qs.exclude(date__gte=today, status__in=["pending", "confirmed"]).order_by("-date", "-start_time")[:20],
        "orders": orders_qs.order_by("-created_at")[:10],
        "packages": PackagePurchase.objects.filter(email_q | Q(user=person)).select_related("package").annotate(
            remaining=Count("vouchers", filter=Q(vouchers__times_used=0, vouchers__is_active=True))),
        "lifetime_pence": orders_qs.filter(status="paid").aggregate(t=Sum("total_pence"))["t"] or 0,
        "session_count": bookings_qs.filter(status__in=["confirmed", "completed"]).count(),
        "last_session": bookings_qs.filter(status="completed").aggregate(d=Max("date"))["d"],
        "password_form": SetPasswordForm(),
    })


@owner_required
def user_create(request):
    from .forms import UserForm

    form = UserForm(request.POST or None, initial={"role": "client"})
    if request.method == "POST" and form.is_valid():
        person = form.save(commit=False)
        person.set_unusable_password()
        person.save()
        if request.POST.get("send_login_link") and person.is_active:
            _send_login_link(request, person)
        messages.success(request, f"{person.full_name or person.email} added.")
        return redirect("dashboard:user_detail", pk=person.pk)
    return render(request, "dashboard/users/form.html", {"form": form, "section": "users"})


@owner_required
def user_edit(request, pk):
    from .forms import UserForm

    person = get_object_or_404(_visible_users(), pk=pk)
    form = UserForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        if person.pk == request.user.pk and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "You can't block your own login.")
        elif person.pk == request.user.pk and form.cleaned_data["role"] == "client":
            form.add_error("role", "You can't remove your own dashboard access.")
        else:
            form.save()
            messages.success(request, "Details saved.")
            return redirect("dashboard:user_detail", pk=pk)
    return render(request, "dashboard/users/form.html", {"form": form, "person": person, "section": "users"})


def _send_login_link(request, person):
    from apps.accounts.services.magic_link import send_magic_link
    try:
        send_magic_link(person, request)
        messages.success(request, f"Login link emailed to {person.email}.")
    except Exception as exc:  # SMTP errors vary by backend
        logger.error("Magic link to %s failed: %s", person.email, exc)
        messages.error(request, "The login link couldn't be sent. Check the email settings and try again.")


@owner_required
@require_POST
def user_send_login_link(request, pk):
    person = get_object_or_404(_visible_users(), pk=pk)
    if not person.is_active:
        messages.error(request, "This person can't log in. Turn on “Can log in” first.")
    else:
        _send_login_link(request, person)
    return redirect("dashboard:user_detail", pk=pk)


@owner_required
@require_POST
def user_set_password(request, pk):
    from .forms import SetPasswordForm

    person = get_object_or_404(_visible_users(), pk=pk)
    form = SetPasswordForm(request.POST)
    if form.is_valid():
        person.set_password(form.cleaned_data["new_password"])
        person.save(update_fields=["password"])
        messages.success(request, "Password updated.")
    else:
        messages.error(request, form.errors["new_password"][0])
    return redirect("dashboard:user_detail", pk=pk)


@owner_required
@require_POST
def user_delete(request, pk):
    person = get_object_or_404(_visible_users(), pk=pk)
    if person.pk == request.user.pk:
        messages.error(request, "You can't delete your own account while you're logged in.")
        return redirect("dashboard:user_detail", pk=pk)
    label = person.full_name or person.email
    person.delete()
    messages.success(request, f"{label} deleted. Their bookings and orders are kept.")
    return redirect("dashboard:user_list")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _bind_partial(form_class, instance, post, files):
    """
    Bind a settings form, filling fields missing from the POST with the
    instance's current values — so a request that only sends some fields
    never blanks the others. Checkboxes and uploads are left alone
    (an absent checkbox means off; an absent upload keeps the file).
    """
    from django import forms as dj_forms
    from django.forms.models import model_to_dict

    data = post.copy()
    current = model_to_dict(instance)
    probe = form_class(instance=instance)
    pence_fields = getattr(probe, "pence_fields", {})
    for name, field in probe.fields.items():
        if name in data or isinstance(field.widget, dj_forms.CheckboxInput) or isinstance(field, dj_forms.FileField):
            continue
        value = field.initial if name in pence_fields else current.get(name)
        if value is not None:
            data[name] = value
    return form_class(data, files, instance=instance)


@owner_required
def settings_view(request):
    from django.forms import modelformset_factory
    from apps.booking.models import BookingSettings, GoogleCalendarConfig
    from apps.legal.models import ContactConfig
    from apps.pages.models import ApproachSection, HeroSection, SiteConfig
    from apps.payments.models import PaymentReminderRule
    from apps.shop.models import ShopSettings
    from . import forms as f

    tabs = {
        "site": (f.SiteConfigForm, SiteConfig, "General details saved."),
        "hero": (f.HeroSectionForm, HeroSection, "Homepage hero saved."),
        "approach": (f.ApproachSectionForm, ApproachSection, "Approach section saved."),
        "booking": (f.BookingSettingsForm, BookingSettings, "Booking rules saved."),
        "shop": (f.ShopSettingsForm, ShopSettings, "Shop settings saved."),
        "contact": (f.ContactConfigForm, ContactConfig, "Contact page saved."),
    }
    ReminderFormSet = modelformset_factory(
        PaymentReminderRule, fields=["delay_hours", "delay_anchor", "is_active"], can_delete=True, extra=0,
    )
    gcal_config = GoogleCalendarConfig.load()
    forms_by_tab = {key: form_class(instance=model.load()) for key, (form_class, model, _) in tabs.items()}
    gcal_form = f.GoogleCalendarForm(instance=gcal_config)
    reminder_formset = ReminderFormSet(prefix="reminder_rules", queryset=PaymentReminderRule.objects.all())
    active_tab = request.session.pop("settings_tab", "site")

    if request.method == "POST":
        section = request.POST.get("_section", "")
        if section in tabs:
            form_class, model, done = tabs[section]
            form = _bind_partial(form_class, model.load(), request.POST, request.FILES)
            if form.is_valid():
                form.save()
                messages.success(request, done)
                request.session["settings_tab"] = section
                return redirect("dashboard:settings")
            forms_by_tab[section] = form
            active_tab = section
        elif section == "gcal":
            post = request.POST.copy()
            # A blank secret keeps the stored one, so the field can stay masked.
            for keep in ("client_id", "client_secret"):
                if not post.get(keep, "").strip():
                    post[keep] = getattr(gcal_config, keep)
            gcal_form = f.GoogleCalendarForm(post, instance=gcal_config)
            if gcal_form.is_valid():
                gcal_form.save()
                messages.success(request, "Google Calendar settings saved.")
                request.session["settings_tab"] = "gcal"
                return redirect("dashboard:settings")
            active_tab = "gcal"
        elif section == "reminders":
            reminder_formset = ReminderFormSet(request.POST, prefix="reminder_rules", queryset=PaymentReminderRule.objects.all())
            if reminder_formset.is_valid():
                reminder_formset.save()
                messages.success(request, "Reminder schedule saved.")
                request.session["settings_tab"] = "reminders"
                return redirect("dashboard:settings")
            active_tab = "reminders"
        else:
            return redirect("dashboard:settings")

    return render(request, "dashboard/settings.html", {
        "section": "settings",
        "forms": forms_by_tab,
        "gcal_form": gcal_form,
        "gcal_config": gcal_config,
        "reminder_formset": reminder_formset,
        "active_tab": active_tab,
    })


# ---------------------------------------------------------------------------
# My account
# ---------------------------------------------------------------------------

@owner_required
def account_view(request):
    from django.contrib.auth import update_session_auth_hash
    from apps.accounts.forms import ChangeEmailForm, ChangePasswordForm, ProfileForm

    user = request.user
    profile_form = ProfileForm(instance=user)
    password_form = ChangePasswordForm(user=user)
    email_form = ChangeEmailForm(user=user)

    if request.method == "POST":
        section = request.POST.get("_section")
        if section == "profile":
            profile_form = ProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile saved.")
                return redirect("dashboard:account")
        elif section == "email":
            email_form = ChangeEmailForm(request.POST, user=user)
            if email_form.is_valid():
                user.email = email_form.cleaned_data["new_email"]
                user.save(update_fields=["email"])
                messages.success(request, "Email updated.")
                return redirect("dashboard:account")
        elif section == "password":
            password_form = ChangePasswordForm(request.POST, user=user)
            if password_form.is_valid():
                user.set_password(password_form.cleaned_data["new_password"])
                user.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated.")
                return redirect("dashboard:account")

    return render(request, "dashboard/account.html", {
        "section": "account",
        "profile_form": profile_form,
        "password_form": password_form,
        "email_form": email_form,
    })


# ---------------------------------------------------------------------------
# Google Calendar OAuth
# ---------------------------------------------------------------------------

def _to_gcal_tab(request):
    request.session["settings_tab"] = "gcal"
    return redirect("dashboard:settings")


@owner_required
def gcal_connect(request):
    from apps.booking.models import GoogleCalendarConfig
    from apps.booking.services.google_calendar import get_auth_url

    config = GoogleCalendarConfig.load()
    if not config.client_id or not config.client_secret:
        messages.error(request, "Add your Google client ID and secret first.")
        return _to_gcal_tab(request)

    redirect_uri = request.build_absolute_uri(reverse("dashboard:gcal_callback"))
    auth_url, code_verifier = get_auth_url(redirect_uri)
    request.session["gcal_code_verifier"] = code_verifier  # PKCE verifier, needed in the callback
    return redirect(auth_url)


@owner_required
def gcal_callback(request):
    from apps.booking.services.google_calendar import handle_oauth_callback

    code = request.GET.get("code")
    if not code:
        messages.error(request, "Google didn't return an authorisation code. Try connecting again.")
        return _to_gcal_tab(request)
    try:
        handle_oauth_callback(code, request.build_absolute_uri(reverse("dashboard:gcal_callback")),
                              code_verifier=request.session.pop("gcal_code_verifier", None))
        messages.success(request, "Google Calendar connected.")
    except Exception as exc:
        logger.error("Google Calendar callback failed: %s", exc)
        messages.error(request, "Connecting to Google Calendar failed. Check the client ID, secret and redirect URL.")
    return _to_gcal_tab(request)


@owner_required
@require_POST
def gcal_disconnect(request):
    from apps.booking.services.google_calendar import disconnect

    disconnect()
    messages.success(request, "Google Calendar disconnected.")
    return _to_gcal_tab(request)


@owner_required
@require_POST
def gcal_sync(request):
    from apps.booking.services.google_calendar import sync_from_calendar

    synced, cancelled = sync_from_calendar()
    messages.success(request, f"Sync finished: {synced} new booking(s) pulled in, {cancelled} cancelled from deleted events.")
    return _to_gcal_tab(request)
