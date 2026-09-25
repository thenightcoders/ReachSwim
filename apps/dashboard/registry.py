"""
Dashboard sections built on the generic Crud engine (see crud.py).

Each class is one sidebar entry. Bespoke screens — bookings, orders, people,
products, messages, settings — live in views.py instead.
"""
from django.db.models import Count, Q
from django.utils import timezone

from apps.booking.models import DAY_CHOICES, Location, Package, RecurringSchedule, SessionPricing, SessionType
from apps.legal.models import LegalPage
from apps.pages.models import ApproachPillar, FAQItem, FooterColumn, Offering, Stat, Testimonial
from apps.payments.models import PackagePurchase, Voucher
from apps.shop.models import ProductCategory

from . import forms
from .crud import BulkAction, Column, Crud, Filter

ACTIVE_FILTER = [("1", "On"), ("0", "Off")]


def _active_filter(field="is_active", label="Status"):
    return Filter(field, label, ACTIVE_FILTER, lambda qs, v, f=field: qs.filter(**{f: v == "1"}))


def _session_types():
    return [(str(s.pk), s.name) for s in SessionType.objects.order_by("order", "name")]


def _locations():
    return [(str(l.pk), l.name) for l in Location.objects.order_by("order", "name")]


def _save_prices(request, rows):
    """Upsert or clear SessionPricing from ``price_<id>`` POST fields. rows: [(key, st, loc)]."""
    from .forms import pounds_to_pence
    from decimal import InvalidOperation
    for key, session_type, location in rows:
        raw = request.POST.get(f"price_{key}", "").strip().replace("£", "")
        if not raw:
            SessionPricing.objects.filter(session_type=session_type, location=location).delete()
            continue
        try:
            pence = pounds_to_pence(raw)
        except (InvalidOperation, ValueError):
            continue
        SessionPricing.objects.update_or_create(
            session_type=session_type, location=location, defaults={"price_pence": pence},
        )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class LocationCrud(Crud):
    key = "location"
    model = Location
    form_class = forms.LocationForm
    section = "locations"
    title = "Pools"
    singular = "pool"
    description = "The venues clients can book. Set what each session costs here, or on the Pricing page."
    empty_text = "Add the pools you teach at so clients can pick one when booking."
    columns = [
        Column("Pool", "name", "title", sort="name", sub=lambda o: o.address.splitlines()[0] if o.address else ""),
        Column("Facilities", lambda o: ", ".join(f for f, on in (("Parking", o.has_parking), ("Hoist", o.has_hoist)) if on) or "—", "muted"),
        Column("Priced sessions", lambda o: o.priced_count, num=True),
        Column("Order", "order", sort="order", num=True),
        Column("Bookable", "is_active", "toggle"),
    ]
    search_fields = ("name", "address")
    search_placeholder = "Search pools"
    filters = [_active_filter()]
    toggle_field = "is_active"
    advanced_fields = ("slug", "order")
    form_extra_template = "dashboard/pricing/_location_prices.html"
    delete_warning = "Bookings and packages at this pool block deletion. Turning it off hides it instead."

    def get_queryset(self, request):
        return Location.objects.annotate(priced_count=Count("pricing", distinct=True)).order_by("order", "name")

    def extra_form_context(self, request, instance):
        existing = {p.session_type_id: p.price_pence for p in SessionPricing.objects.filter(location=instance)} if instance else {}
        return {"price_rows": [
            {"key": st.pk, "label": st.name, "sub": f"{st.duration_minutes} min", "pence": existing.get(st.pk)}
            for st in SessionType.objects.order_by("order", "name")
        ]}

    def after_save(self, request, obj, created):
        _save_prices(request, [(st.pk, st, obj) for st in SessionType.objects.all()])


class SessionTypeCrud(Crud):
    key = "sessiontype"
    model = SessionType
    form_class = forms.SessionTypeForm
    section = "sessiontypes"
    title = "Session types"
    singular = "session type"
    description = "What clients can book, like 1:1 lessons or small groups."
    empty_text = "Create a session type, then give it a price at each pool."
    columns = [
        Column("Session type", "name", "title", sort="name"),
        Column("Length", lambda o: f"{o.duration_minutes} min", sort="duration_minutes"),
        Column("Spaces", "max_participants", sort="max_participants", num=True),
        Column("Pools priced", lambda o: o.priced_count, num=True),
        Column("Bookable", "is_active", "toggle"),
    ]
    search_fields = ("name",)
    search_placeholder = "Search session types"
    filters = [_active_filter()]
    toggle_field = "is_active"
    advanced_fields = ("slug", "order")
    form_extra_template = "dashboard/pricing/_location_prices.html"
    delete_warning = "Existing bookings of this type block deletion. Turning it off hides it instead."
    help_tips = (
        "Leave a pool's price blank to stop this session being bookable there.",
        "Timetable slots decide which days and times are offered.",
    )

    def get_queryset(self, request):
        return SessionType.objects.annotate(priced_count=Count("pricing", distinct=True)).order_by("order", "name")

    def extra_form_context(self, request, instance):
        existing = {p.location_id: p.price_pence for p in SessionPricing.objects.filter(session_type=instance)} if instance else {}
        return {"price_rows": [
            {"key": loc.pk, "label": loc.name, "sub": "" if loc.is_active else "Not bookable", "pence": existing.get(loc.pk)}
            for loc in Location.objects.order_by("order", "name")
        ]}

    def after_save(self, request, obj, created):
        _save_prices(request, [(loc.pk, obj, loc) for loc in Location.objects.all()])


class ScheduleCrud(Crud):
    key = "schedule"
    model = RecurringSchedule
    form_class = forms.RecurringScheduleForm
    section = "schedules"
    title = "Timetable"
    singular = "timetable slot"
    description = "Your repeating weekly slots. Clients can book these on any date inside the booking window."
    empty_text = "Add the times you teach each week."
    list_template = "dashboard/schedules/board.html"
    columns = [Column("Slot", str, "title")]
    filters = [
        Filter("location", "Pool", _locations, "location_id"),
        Filter("session_type", "Session", _session_types, "session_type_id"),
    ]
    toggle_field = "is_active"
    per_page = 500
    fieldsets = [(None, ["session_type", "location", "day_of_week"]), ("Time and spaces", ["start_time", "end_time", "max_capacity", "is_active"])]

    def get_queryset(self, request):
        return RecurringSchedule.objects.select_related("session_type", "location").order_by("day_of_week", "start_time")

    def get_form(self, request, instance=None):
        form = super().get_form(request, instance)
        if instance is None and request.method == "GET" and request.GET.get("day", "").isdigit():
            form.initial["day_of_week"] = int(request.GET["day"])
        return form

    def extra_list_context(self, request):
        return {"days": DAY_CHOICES}


class PackageCrud(Crud):
    key = "package"
    model = Package
    form_class = forms.PackageForm
    section = "packages"
    title = "Packages"
    singular = "package"
    description = "Bundles of sessions sold at a discount. Each purchase becomes a set of single-use credits."
    empty_text = "Create a bundle, like 5 lessons for the price of 4."
    columns = [
        Column("Package", "name", "title", sort="name", sub=lambda o: f"{o.session_type} at {o.location}"),
        Column("Sessions", "session_count", sort="session_count", num=True),
        Column("Price", "price_pence", "money", sort="price_pence", num=True, sub=lambda o: f"{o.per_session_display} each"),
        Column("Valid for", lambda o: f"{o.valid_days} days", sort="valid_days"),
        Column("Sold", lambda o: o.sold, num=True),
        Column("On sale", "is_active", "toggle"),
    ]
    search_fields = ("name",)
    search_placeholder = "Search packages"
    filters = [
        _active_filter(label="On sale"),
        Filter("session_type", "Session", _session_types, "session_type_id"),
        Filter("location", "Pool", _locations, "location_id"),
    ]
    toggle_field = "is_active"
    advanced_fields = ("order",)
    delete_warning = "Packages that have been bought can't be deleted. Take them off sale instead."

    def get_queryset(self, request):
        return (Package.objects.select_related("session_type", "location")
                .annotate(sold=Count("purchases", distinct=True)).order_by("order", "name"))


# ---------------------------------------------------------------------------
# Clients: vouchers & package credits
# ---------------------------------------------------------------------------

def voucher_discount(v):
    if v.discount_type == Voucher.DISCOUNT_PERCENTAGE:
        return f"{v.discount_value}% off"
    if v.discount_type == Voucher.DISCOUNT_FIXED:
        from apps.payments.templatetags.payment_tags import pence_to_pounds
        return f"{pence_to_pounds(v.discount_value)} off"
    return "Free session"


def voucher_status(v):
    now = timezone.now()
    if not v.is_active:
        return ("Off", "inactive")
    if v.valid_until and now > v.valid_until:
        return ("Expired", "expired")
    if now < v.valid_from:
        return ("Scheduled", "pending")
    if v.max_uses and v.times_used >= v.max_uses:
        return ("Used up", "completed")
    return ("Live", "active")


def _voucher_state_filter(qs, value):
    now = timezone.now()
    live = Q(is_active=True, valid_from__lte=now) & (Q(valid_until__isnull=True) | Q(valid_until__gte=now))
    if value == "live":
        from django.db.models import F
        return qs.filter(live).filter(Q(max_uses=0) | Q(times_used__lt=F("max_uses")))
    if value == "expired":
        return qs.filter(valid_until__lt=now)
    if value == "off":
        return qs.filter(is_active=False)
    return qs


def _reset_usage(request, qs):
    n = qs.update(times_used=0)
    return f"Usage reset on {n} voucher(s)."


class VoucherCrud(Crud):
    key = "voucher"
    model = Voucher
    form_class = forms.VoucherForm
    section = "vouchers"
    title = "Vouchers"
    singular = "voucher"
    description = "Discount codes clients enter at checkout. Package credits are listed too, so you can see every code in one place."
    empty_text = "Create a code for a promotion, a friend pass, or to say sorry for a cancelled lesson."
    columns = [
        Column("Code", "code", "title", sort="code", sub=lambda v: "Package credit" if v.package_purchase_id else ""),
        Column("Discount", voucher_discount),
        Column("Limited to", lambda v: ", ".join(str(x) for x in (v.allowed_email, v.session_type, v.location) if x) or "Anyone", "muted"),
        Column("Used", lambda v: f"{v.times_used} / {v.max_uses or '∞'}", sort="times_used", num=True),
        Column("Expires", "valid_until", "date", sort="valid_until"),
        Column("Status", voucher_status, "badge"),
    ]
    search_fields = ("code", "allowed_email")
    search_placeholder = "Search code or email"
    filters = [
        Filter("state", "Status", [("live", "Live"), ("expired", "Expired"), ("off", "Off")], _voucher_state_filter),
        Filter("source", "Type", [("manual", "Promo codes"), ("package", "Package credits")],
               lambda qs, v: qs.filter(package_purchase__isnull=(v == "manual"))),
        Filter("discount_type", "Discount", [(k, l) for k, l in (
            (Voucher.DISCOUNT_PERCENTAGE, "Percentage"), (Voucher.DISCOUNT_FIXED, "Fixed amount"), (Voucher.DISCOUNT_FULL, "Free session"))]),
    ]
    toggle_field = "is_active"
    fieldsets = [
        (None, ["code", "discount_type", "percent", "amount", "is_active"]),
        ("Who can use it", ["allowed_email", "session_type", "location", "min_order"]),
        ("When and how often", ["valid_from", "valid_until", "max_uses"]),
    ]
    form_side_template = "dashboard/vouchers/_side.html"

    def get_queryset(self, request):
        return Voucher.objects.select_related("session_type", "location", "package_purchase").order_by("-created_at")

    def extra_bulk_actions(self):
        return [BulkAction("reset", "Reset usage", _reset_usage, confirm="Set the usage count back to 0 for the selected vouchers?")]


def purchase_status(p):
    if not p.is_active:
        return ("Frozen", "inactive")
    if p.is_expired:
        return ("Expired", "expired")
    if p.remaining == 0:
        return ("Used up", "completed")
    return ("Active", "active")


class PackagePurchaseCrud(Crud):
    key = "packagepurchase"
    model = PackagePurchase
    form_class = forms.PackagePurchaseForm
    section = "packagepurchases"
    title = "Package credits"
    singular = "package purchase"
    description = "Packages clients have bought and how many sessions they have left."
    empty_text = "When a client buys a package, it appears here. You can also grant one yourself."
    list_template = "dashboard/packagepurchases/list.html"
    can_create = False
    columns = [
        Column("Client", "client_name", "title", sort="client_name", sub="client_email"),
        Column("Package", "package__name", sub=lambda p: f"{p.package.session_type} at {p.package.location}"),
        Column("Credits left", lambda p: f"{p.remaining} of {p.total}", num=True),
        Column("Paid", "amount_pence", "money", sort="amount_pence", num=True),
        Column("Bought", "purchased_at", "date", sort="purchased_at"),
        Column("Expires", "expires_at", "date", sort="expires_at"),
        Column("Status", purchase_status, "badge"),
    ]
    search_fields = ("client_name", "client_email", "package__name")
    search_placeholder = "Search client or package"
    filters = [
        Filter("state", "Status", [("usable", "Has credits"), ("expired", "Expired"), ("frozen", "Frozen")],
               lambda qs, v: {
                   "usable": qs.filter(is_active=True, expires_at__gte=timezone.now(), remaining__gt=0),
                   "expired": qs.filter(expires_at__lt=timezone.now()),
                   "frozen": qs.filter(is_active=False),
               }.get(v, qs)),
        Filter("package", "Package", lambda: [(str(p.pk), p.name) for p in Package.objects.order_by("name")], "package_id"),
    ]
    toggle_field = "is_active"
    form_side_template = "dashboard/packagepurchases/_credits.html"
    delete_warning = "This also deletes all of its unused credit codes."

    def get_queryset(self, request):
        return (PackagePurchase.objects.select_related("package__session_type", "package__location", "user")
                .annotate(total=Count("vouchers", distinct=True),
                          remaining=Count("vouchers", filter=Q(vouchers__times_used=0, vouchers__is_active=True), distinct=True))
                .order_by("-purchased_at"))

    def extra_form_context(self, request, instance):
        return {"credits": instance.vouchers.order_by("times_used", "code") if instance else []}

    def _bulk_set(self, value):
        def run(request, qs):
            n = qs.update(is_active=value)
            Voucher.objects.filter(package_purchase__in=qs, times_used=0).update(is_active=value)
            return f"{n} package(s) {'reactivated' if value else 'frozen'}."
        return run

    def toggle_view(self, request, pk):
        response = super().toggle_view(request, pk)
        purchase = PackagePurchase.objects.get(pk=pk)
        purchase.vouchers.filter(times_used=0).update(is_active=purchase.is_active)
        return response


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------

class CategoryCrud(Crud):
    key = "category"
    model = ProductCategory
    form_class = forms.ProductCategoryForm
    section = "categories"
    title = "Categories"
    singular = "category"
    description = "The filter tabs in your shop."
    columns = [
        Column("Category", "name", "title", sort="name"),
        Column("Products", lambda c: c.product_total, num=True),
        Column("Order", "order", sort="order", num=True),
    ]
    search_fields = ("name",)
    advanced_fields = ("slug",)
    delete_warning = "Categories that still contain products can't be deleted."

    def get_queryset(self, request):
        return ProductCategory.objects.annotate(product_total=Count("products")).order_by("order", "name")


# ---------------------------------------------------------------------------
# Website content
# ---------------------------------------------------------------------------

class OfferingCrud(Crud):
    key = "offering"
    model = Offering
    form_class = forms.OfferingForm
    section = "offerings"
    title = "Offerings"
    singular = "offering"
    description = "The service cards on your homepage."
    columns = [
        Column("Offering", "image", "thumb"),
        Column("Tag", "tag", "muted"),
        Column("Details", "meta_items", "muted"),
        Column("Order", "order", sort="order", num=True),
    ]
    advanced_fields = ("photo_class", "photo_label", "order")


class StatCrud(Crud):
    key = "stat"
    model = Stat
    form_class = forms.StatForm
    section = "stats"
    title = "Stats"
    singular = "stat"
    description = "The numbers shown in the Approach section, like adults coached."
    columns = [
        Column("Figure", "value", "title"),
        Column("Label", "label"),
        Column("Order", "order", sort="order", num=True),
    ]


class PillarCrud(Crud):
    key = "pillar"
    model = ApproachPillar
    form_class = forms.ApproachPillarForm
    section = "pillars"
    title = "Approach pillars"
    singular = "pillar"
    description = "The numbered principles in the Approach section."
    columns = [
        Column("Number", "number", "muted"),
        Column("Pillar", "title", "title"),
        Column("Order", "order", sort="order", num=True),
    ]


class TestimonialCrud(Crud):
    key = "testimonial"
    model = Testimonial
    form_class = forms.TestimonialForm
    section = "testimonials"
    title = "Testimonials"
    singular = "testimonial"
    description = "Quotes from clients on your homepage."
    columns = [
        Column("From", "author_name", "title", sub="author_role"),
        Column("Quote", lambda t: (t.quote[:90] + "…") if len(t.quote) > 90 else t.quote, "muted"),
        Column("Order", "order", sort="order", num=True),
        Column("Shown", "is_active", "toggle"),
    ]
    search_fields = ("author_name", "quote")
    search_placeholder = "Search testimonials"
    filters = [_active_filter(label="Shown")]
    toggle_field = "is_active"
    advanced_fields = ("order",)

    def str_for(self, obj):
        return obj.author_name


class FAQCrud(Crud):
    key = "faq"
    model = FAQItem
    form_class = forms.FAQItemForm
    section = "faqs"
    title = "FAQs"
    singular = "question"
    description = "Questions and answers on your homepage."
    columns = [
        Column("Question", "question", "title"),
        Column("Order", "order", sort="order", num=True),
        Column("Shown", "is_active", "toggle"),
    ]
    search_fields = ("question", "answer")
    search_placeholder = "Search questions"
    filters = [_active_filter(label="Shown")]
    toggle_field = "is_active"
    advanced_fields = ("order",)


class LegalPageCrud(Crud):
    key = "legalpage"
    model = LegalPage
    form_class = forms.LegalPageForm
    section = "legalpages"
    title = "Legal pages"
    singular = "page"
    description = "Privacy policy, terms, and other policy pages. HTML is allowed in the content."
    columns = [
        Column("Page", "title", "title", sort="title", sub=lambda p: p.get_absolute_url()),
        Column("Last edited", "updated_at", "datetime", sort="updated_at"),
        Column("Published", "is_active", "toggle"),
    ]
    search_fields = ("title", "content")
    toggle_field = "is_active"
    advanced_fields = ("slug",)
    form_side_template = "dashboard/legalpages/_side.html"


class FooterCrud(Crud):
    key = "footer"
    model = FooterColumn
    form_class = forms.FooterColumnForm
    section = "footer"
    title = "Footer links"
    singular = "footer column"
    description = "The link columns at the bottom of every page."
    form_template = "dashboard/footer/form.html"
    columns = [
        Column("Column", "title", "title"),
        Column("Links", lambda c: ", ".join(l.label for l in c.links.all()) or "No links yet", "muted"),
        Column("Order", "order", sort="order", num=True),
    ]

    def get_queryset(self, request):
        return FooterColumn.objects.prefetch_related("links").order_by("order")

    def get_formsets(self, request, instance):
        data = request.POST if request.method == "POST" else None
        return {"links": forms.FooterLinkFormSet(data, instance=instance, prefix="links")}


SECTIONS = [
    (LocationCrud, "locations"),
    (SessionTypeCrud, "session-types"),
    (ScheduleCrud, "timetable"),
    (PackageCrud, "packages"),
    (VoucherCrud, "vouchers"),
    (PackagePurchaseCrud, "package-credits"),
    (CategoryCrud, "categories"),
    (OfferingCrud, "website/offerings"),
    (StatCrud, "website/stats"),
    (PillarCrud, "website/pillars"),
    (TestimonialCrud, "website/testimonials"),
    (FAQCrud, "website/faqs"),
    (LegalPageCrud, "website/legal"),
    (FooterCrud, "website/footer"),
]


def urlpatterns():
    patterns = []
    for crud, prefix in SECTIONS:
        patterns += crud.urls(prefix)
    return patterns
