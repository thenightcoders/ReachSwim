"""
Dashboard forms.

Money is always entered in pounds and stored in pence: declare a MoneyField on
the form and map it to the model's *_pence attribute via ``pence_fields``.
Widgets carry no CSS classes — the dashboard stylesheet styles inputs inside
``.field`` wrappers (see templates/dashboard/includes/field.html).
"""
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.booking.models import (
    Booking, BookingSettings, GoogleCalendarConfig, Location, Package,
    RecurringSchedule, SessionType,
)
from apps.legal.models import ContactConfig, LegalPage
from apps.pages.models import (
    ApproachPillar, ApproachSection, FAQItem, FooterColumn, FooterLink,
    HeroSection, Offering, SiteConfig, Stat, Testimonial,
)
from apps.payments.models import PackagePurchase, Voucher
from apps.shop.models import Product, ProductCategory, ShopSettings

User = get_user_model()

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


def pounds_to_pence(value) -> int:
    return int((Decimal(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


class MoneyField(forms.DecimalField):
    """Amount in pounds (2dp). Rendered with a currency prefix by field.html."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("min_value", Decimal("0"))
        kwargs.setdefault("max_digits", 9)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("widget", forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}))
        super().__init__(*args, **kwargs)


class PenceFieldsMixin:
    """
    Maps MoneyField form fields ↔ integer pence model attributes.

    ``pence_fields = {"price": "price_pence"}``. Blank money inputs store None
    when the model attribute is nullable, otherwise 0.
    """
    pence_fields: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        for form_name, attr in self.pence_fields.items():
            pence = getattr(instance, attr, None) if instance is not None else None
            if pence is not None and (instance.pk or pence):
                self.fields[form_name].initial = Decimal(pence) / 100

    def _apply_pence(self, instance):
        for form_name, attr in self.pence_fields.items():
            value = self.cleaned_data.get(form_name)
            if value is None:
                nullable = instance._meta.get_field(attr).null
                setattr(instance, attr, None if nullable else 0)
            else:
                setattr(instance, attr, pounds_to_pence(value))
        return instance

    def save(self, commit=True):
        instance = self._apply_pence(super().save(commit=False))
        if commit:
            instance.save()
            self.save_m2m()
        return instance


def _dt_widget():
    return forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "slug", "address", "description", "has_parking", "has_hoist", "is_active", "order"]
        labels = {"name": "Pool name", "has_parking": "Parking available", "has_hoist": "Pool hoist",
                  "is_active": "Open for booking", "slug": "URL slug", "order": "Display order"}
        help_texts = {
            "address": "Include the postcode so clients can find it.",
            "has_hoist": "Shows an accessibility badge on this pool.",
            "is_active": "Closed pools are hidden from the booking page.",
            "order": "Lower numbers appear first.",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Ironmonger Row Baths"}),
            "slug": forms.TextInput(attrs={"data-slug-from": "id_name"}),
            "address": forms.Textarea(attrs={"rows": 3}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class SessionTypeForm(forms.ModelForm):
    class Meta:
        model = SessionType
        fields = ["name", "slug", "description", "duration_minutes", "max_participants", "is_active", "order"]
        labels = {"duration_minutes": "Length (minutes)", "is_active": "Bookable",
                  "slug": "URL slug", "order": "Display order"}
        help_texts = {
            "max_participants": "1 for private lessons, more for small groups.",
            "is_active": "Turn off to hide this session type from the booking page.",
            "order": "Lower numbers appear first.",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. 1:1 lesson"}),
            "slug": forms.TextInput(attrs={"data-slug-from": "id_name"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class RecurringScheduleForm(forms.ModelForm):
    class Meta:
        model = RecurringSchedule
        fields = ["session_type", "location", "day_of_week", "start_time", "end_time", "max_capacity", "is_active"]
        labels = {"location": "Pool", "day_of_week": "Day", "max_capacity": "Spaces", "is_active": "Taking bookings"}
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "End time must be after the start time.")
        return data


class PackageForm(PenceFieldsMixin, forms.ModelForm):
    pence_fields = {"price": "price_pence"}
    price = MoneyField(label="Price")

    class Meta:
        model = Package
        fields = ["name", "session_type", "location", "session_count", "price", "valid_days", "is_active", "order"]
        labels = {"location": "Pool", "session_count": "Sessions included", "valid_days": "Valid for (days)",
                  "is_active": "On sale", "order": "Display order"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. 5 × 1:1 lessons"})}


# ---------------------------------------------------------------------------
# Bookings & clients
# ---------------------------------------------------------------------------

class BookingForm(PenceFieldsMixin, forms.ModelForm):
    pence_fields = {"amount": "amount_pence"}
    amount = MoneyField(label="Amount paid", required=False)

    class Meta:
        model = Booking
        fields = [
            "session_type", "location", "date", "start_time", "end_time",
            "client_name", "client_email", "client_phone", "user", "status", "amount", "notes",
        ]
        labels = {"location": "Pool", "user": "Linked account", "notes": "Internal notes"}
        help_texts = {"user": "Optional. Link to a registered client so it shows in their account."}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.order_by("full_name", "email")
        self.fields["user"].required = False
        self.fields["user"].empty_label = "Not linked to an account"

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "End time must be after the start time.")
        return data


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "phone", "role", "is_active"]
        labels = {"is_active": "Can log in"}
        help_texts = {
            "role": "Owners and staff can open this dashboard.",
            "is_active": "Turn off to block logins without deleting history.",
        }


class SetPasswordForm(forms.Form):
    new_password = forms.CharField(
        label="New password", min_length=8, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 8 characters. Share it with the client securely.",
    )


class VoucherForm(PenceFieldsMixin, forms.ModelForm):
    """
    discount_value means % for percentage vouchers and pence for fixed ones,
    so the form exposes two friendlier inputs and folds them back on save.
    """
    pence_fields = {"min_order": "min_order_pence"}
    percent = forms.IntegerField(label="Percent off", required=False, min_value=1, max_value=100,
                                 widget=forms.NumberInput(attrs={"placeholder": "e.g. 10"}))
    amount = MoneyField(label="Amount off", required=False)
    min_order = MoneyField(label="Minimum spend", required=False, help_text="Leave blank for no minimum.")

    class Meta:
        model = Voucher
        fields = [
            "code", "discount_type", "percent", "amount", "allowed_email", "session_type", "location",
            "max_uses", "valid_from", "valid_until", "min_order", "is_active",
        ]
        labels = {
            "discount_type": "Discount", "allowed_email": "Only for this email",
            "session_type": "Only for session type", "location": "Only at pool",
            "max_uses": "Usage limit", "valid_until": "Expires", "valid_from": "Starts", "is_active": "Active",
        }
        help_texts = {"max_uses": "0 means unlimited.", "valid_until": "Leave blank to never expire."}
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "SUMMER10", "style": "text-transform:uppercase"}),
            "valid_from": _dt_widget(),
            "valid_until": _dt_widget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["discount_type"].choices = [
            (Voucher.DISCOUNT_PERCENTAGE, "Percentage off"),
            (Voucher.DISCOUNT_FIXED, "Fixed amount off"),
            (Voucher.DISCOUNT_FULL, "Free (whole session)"),
        ]
        self.fields["valid_from"].input_formats = [DATETIME_FORMAT]
        self.fields["valid_until"].input_formats = [DATETIME_FORMAT]
        self.fields["session_type"].empty_label = "Any session type"
        self.fields["location"].empty_label = "Any pool"
        if not self.instance.pk:
            self.fields["valid_from"].initial = timezone.localtime().strftime(DATETIME_FORMAT)
        else:
            if self.instance.discount_type == Voucher.DISCOUNT_PERCENTAGE:
                self.fields["percent"].initial = self.instance.discount_value
            elif self.instance.discount_type == Voucher.DISCOUNT_FIXED:
                self.fields["amount"].initial = Decimal(self.instance.discount_value) / 100

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean(self):
        data = super().clean()
        kind = data.get("discount_type")
        if kind == Voucher.DISCOUNT_PERCENTAGE and not data.get("percent"):
            self.add_error("percent", "Enter how much percent to take off.")
        if kind == Voucher.DISCOUNT_FIXED and not data.get("amount"):
            self.add_error("amount", "Enter the amount to take off.")
        start, end = data.get("valid_from"), data.get("valid_until")
        if start and end and end <= start:
            self.add_error("valid_until", "Expiry must be after the start date.")
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        kind = instance.discount_type
        if kind == Voucher.DISCOUNT_PERCENTAGE:
            instance.discount_value = self.cleaned_data["percent"]
        elif kind == Voucher.DISCOUNT_FIXED:
            instance.discount_value = pounds_to_pence(self.cleaned_data["amount"])
        else:
            instance.discount_value = 0
        if commit:
            instance.save()
        return instance


class PackagePurchaseForm(forms.ModelForm):
    class Meta:
        model = PackagePurchase
        fields = ["client_name", "client_email", "user", "expires_at", "is_active"]
        labels = {"user": "Linked account", "expires_at": "Credits expire", "is_active": "Credits usable"}
        help_texts = {"is_active": "Turn off to freeze all remaining credits."}
        widgets = {"expires_at": _dt_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expires_at"].input_formats = [DATETIME_FORMAT]
        self.fields["user"].queryset = User.objects.order_by("full_name", "email")
        self.fields["user"].required = False
        self.fields["user"].empty_label = "Not linked to an account"

    def save(self, commit=True):
        purchase = super().save(commit)
        if commit:
            # Keep the credit vouchers in step with the purchase.
            purchase.vouchers.filter(times_used=0).update(
                valid_until=purchase.expires_at,
                allowed_email=purchase.client_email.strip().lower(),
                is_active=purchase.is_active,
            )
        return purchase


class GrantPackageForm(forms.Form):
    package = forms.ModelChoiceField(queryset=Package.objects.select_related("session_type", "location"),
                                     empty_label="Choose a package")
    client_name = forms.CharField(max_length=200)
    client_email = forms.EmailField()
    complimentary = forms.BooleanField(
        required=False, initial=True, label="Complimentary",
        help_text="Records the purchase as £0. Turn off if they paid you directly.",
    )


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------

class ProductForm(PenceFieldsMixin, forms.ModelForm):
    """Category arrives as free text via ``category_name`` (see views._resolve_category)."""
    pence_fields = {"price": "price_pence", "shipping": "shipping_override_pence"}
    price = MoneyField(label="Price")
    shipping = MoneyField(label="Shipping override", required=False,
                          help_text="Only if this product ships at a different rate. Blank uses the shop default.")

    class Meta:
        model = Product
        fields = ["name", "slug", "category", "description", "color", "image", "stock", "is_active",
                  "photo_class", "order"]
        labels = {"color": "Colour", "is_active": "Visible in shop", "slug": "URL slug",
                  "photo_class": "Placeholder style", "order": "Display order"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Classic silicone cap"}),
            "slug": forms.TextInput(attrs={"data-slug-from": "id_name"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "color": forms.TextInput(attrs={"placeholder": "e.g. Reef blue"}),
            "photo_class": forms.TextInput(attrs={"placeholder": "e.g. photo--tile"}),
        }


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["name", "slug", "order"]
        labels = {"slug": "URL slug", "order": "Display order"}
        widgets = {"slug": forms.TextInput(attrs={"data-slug-from": "id_name"})}


# ---------------------------------------------------------------------------
# Website content
# ---------------------------------------------------------------------------

class OfferingForm(forms.ModelForm):
    class Meta:
        model = Offering
        fields = ["title", "tag", "description", "meta_items", "image", "photo_label", "photo_class", "order"]
        labels = {"meta_items": "Details", "photo_class": "Placeholder style", "order": "Display order"}
        help_texts = {"meta_items": "Comma-separated, e.g. 60 min, East London, From £80"}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class StatForm(forms.ModelForm):
    class Meta:
        model = Stat
        fields = ["value", "label", "order"]
        labels = {"order": "Display order"}


class ApproachPillarForm(forms.ModelForm):
    class Meta:
        model = ApproachPillar
        fields = ["number", "title", "description", "order"]
        labels = {"order": "Display order"}
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class TestimonialForm(forms.ModelForm):
    class Meta:
        model = Testimonial
        fields = ["quote", "author_name", "author_role", "is_active", "order"]
        labels = {"author_name": "Name", "author_role": "Who they are", "is_active": "Show on website",
                  "order": "Display order"}
        widgets = {"quote": forms.Textarea(attrs={"rows": 4})}


class FAQItemForm(forms.ModelForm):
    class Meta:
        model = FAQItem
        fields = ["question", "answer", "is_active", "order"]
        labels = {"is_active": "Show on website", "order": "Display order"}
        widgets = {"answer": forms.Textarea(attrs={"rows": 5})}


class LegalPageForm(forms.ModelForm):
    class Meta:
        model = LegalPage
        fields = ["title", "slug", "content", "is_active"]
        labels = {"slug": "URL slug", "is_active": "Published"}
        widgets = {
            "slug": forms.TextInput(attrs={"data-slug-from": "id_title"}),
            "content": forms.Textarea(attrs={"rows": 18}),
        }


class FooterColumnForm(forms.ModelForm):
    class Meta:
        model = FooterColumn
        fields = ["title", "order"]
        labels = {"title": "Column heading", "order": "Display order"}


FooterLinkFormSet = forms.inlineformset_factory(
    FooterColumn, FooterLink, fields=["label", "url", "order"], extra=0, can_delete=True,
    widgets={"url": forms.TextInput(attrs={"placeholder": "/booking/ or https://…"})},
)


# ---------------------------------------------------------------------------
# Settings singletons — one form per settings tab
# ---------------------------------------------------------------------------

class SiteConfigForm(forms.ModelForm):
    class Meta:
        model = SiteConfig
        fields = [
            "site_name", "tagline", "established_year", "currency", "logo", "favicon",
            "email", "phone", "location_text", "meta_description",
            "whatsapp_url", "instagram_url", "facebook_url", "twitter_url", "linkedin_url",
            "youtube_url", "tiktok_url", "snapchat_url",
        ]
        labels = {"location_text": "Location shown on site", "twitter_url": "X / Twitter URL",
                  "meta_description": "Search engine description"}
        help_texts = {"currency": "Display only. Payments are always taken in GBP."}
        widgets = {"meta_description": forms.Textarea(attrs={"rows": 2})}


class HeroSectionForm(forms.ModelForm):
    class Meta:
        model = HeroSection
        fields = ["headline", "headline_accent", "subheadline", "background_image",
                  "cta_primary_text", "cta_secondary_text", "strip_items"]
        labels = {"headline_accent": "Accent words", "cta_primary_text": "Main button",
                  "cta_secondary_text": "Second button", "strip_items": "Highlights strip"}
        help_texts = {"strip_items": "Separate items with a | character."}
        widgets = {"subheadline": forms.Textarea(attrs={"rows": 3})}


class ApproachSectionForm(forms.ModelForm):
    class Meta:
        model = ApproachSection
        fields = ["kicker", "headline", "headline_accent", "body"]
        labels = {"kicker": "Small heading", "headline_accent": "Accent words"}
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}


class BookingSettingsForm(forms.ModelForm):
    class Meta:
        model = BookingSettings
        fields = ["booking_page_heading", "booking_page_subheading", "max_advance_days", "min_advance_hours",
                  "cancellation_hours", "slot_duration_minutes", "draft_lifetime_days"]
        labels = {
            "booking_page_heading": "Page heading", "booking_page_subheading": "Page introduction",
            "max_advance_days": "Book up to (days ahead)", "min_advance_hours": "Minimum notice (hours)",
            "cancellation_hours": "Free cancellation until (hours before)",
            "slot_duration_minutes": "Default slot length (minutes)", "draft_lifetime_days": "Keep unfinished bookings for (days)",
        }
        widgets = {"booking_page_subheading": forms.Textarea(attrs={"rows": 2})}


class ShopSettingsForm(PenceFieldsMixin, forms.ModelForm):
    pence_fields = {"free_shipping_threshold": "free_shipping_threshold_pence", "shipping_rate": "shipping_rate_pence"}
    free_shipping_threshold = MoneyField(label="Free shipping over")
    shipping_rate = MoneyField(label="Standard shipping")

    class Meta:
        model = ShopSettings
        fields = ["kicker", "heading", "heading_emphasis", "subheading", "free_shipping_note",
                  "free_shipping_threshold", "shipping_rate"]
        labels = {"kicker": "Small heading", "heading_emphasis": "Accent words", "free_shipping_note": "Shipping banner"}
        widgets = {"subheading": forms.Textarea(attrs={"rows": 2})}


class ContactConfigForm(forms.ModelForm):
    class Meta:
        model = ContactConfig
        fields = ["heading", "subheading", "email", "phone", "address", "success_message"]
        labels = {"success_message": "Message after sending"}
        widgets = {"subheading": forms.Textarea(attrs={"rows": 2}), "address": forms.Textarea(attrs={"rows": 3})}


class GoogleCalendarForm(forms.ModelForm):
    class Meta:
        model = GoogleCalendarConfig
        fields = ["client_id", "client_secret", "calendar_id", "sync_deletions_from_calendar"]
        labels = {"sync_deletions_from_calendar": "Cancel bookings deleted from the calendar"}
        widgets = {"client_secret": forms.PasswordInput(render_value=True)}
