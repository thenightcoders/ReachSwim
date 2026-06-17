from django import forms
from apps.booking.models import Location, SessionType

class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'slug', 'address', 'description', 'has_parking', 'has_hoist', 'is_active', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'dash-input'}),
            'slug': forms.TextInput(attrs={'class': 'dash-input'}),
            'address': forms.Textarea(attrs={'class': 'dash-textarea', 'rows': 3}),
            'description': forms.Textarea(attrs={'class': 'dash-textarea', 'rows': 4}),
            'has_parking': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
            'has_hoist': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
            'order': forms.NumberInput(attrs={'class': 'dash-input'}),
        }

class SessionTypeForm(forms.ModelForm):
    class Meta:
        model = SessionType
        fields = ['name', 'slug', 'description', 'duration_minutes', 'max_participants', 'is_active', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'dash-input'}),
            'slug': forms.TextInput(attrs={'class': 'dash-input'}),
            'description': forms.Textarea(attrs={'class': 'dash-textarea', 'rows': 4}),
            'duration_minutes': forms.NumberInput(attrs={'class': 'dash-input'}),
            'max_participants': forms.NumberInput(attrs={'class': 'dash-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
            'order': forms.NumberInput(attrs={'class': 'dash-input'}),
        }

from apps.booking.models import RecurringSchedule

class RecurringScheduleForm(forms.ModelForm):
    class Meta:
        model = RecurringSchedule
        fields = ['session_type', 'location', 'day_of_week', 'start_time', 'end_time', 'max_capacity', 'is_active']
        widgets = {
            'session_type': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'location': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'day_of_week': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'start_time': forms.TimeInput(attrs={'class': 'dash-input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'dash-input', 'type': 'time'}),
            'max_capacity': forms.NumberInput(attrs={'class': 'dash-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
        }

from django.contrib.auth import get_user_model
User = get_user_model()

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'full_name', 'phone', 'role', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'dash-input'}),
            'full_name': forms.TextInput(attrs={'class': 'dash-input'}),
            'phone': forms.TextInput(attrs={'class': 'dash-input'}),
            'role': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
        }

from apps.shop.models import Product
from decimal import Decimal

class ProductForm(forms.ModelForm):
    """
    Non-technical product form.
    - price is entered in pounds (£), converted to pence on save
    - slug, photo_class, order are advanced fields (hidden by default in the template)
    """
    price = forms.DecimalField(
        label="Price",
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=8,
        widget=forms.NumberInput(attrs={
            'class': 'dash-input',
            'step': '0.01',
            'placeholder': '0.00',
            'min': '0',
        }),
    )
    shipping = forms.DecimalField(
        label="Custom shipping (£)",
        required=False,
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=8,
        widget=forms.NumberInput(attrs={
            'class': 'dash-input',
            'step': '0.01',
            'placeholder': 'Leave blank to use shop default',
            'min': '0',
        }),
    )

    class Meta:
        model = Product
        fields = ['name', 'slug', 'category', 'description', 'color',
                  'image', 'stock', 'is_active', 'photo_class', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'dash-input', 'placeholder': 'e.g. Classic Silicone Cap'}),
            'slug': forms.TextInput(attrs={'class': 'dash-input'}),
            'category': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'description': forms.Textarea(attrs={'class': 'dash-textarea', 'rows': 3, 'placeholder': 'Short description shown on the product card.'}),
            'color': forms.TextInput(attrs={'class': 'dash-input', 'placeholder': 'e.g. Reef Blue'}),
            'image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'stock': forms.NumberInput(attrs={'class': 'dash-input', 'min': '0'}),
            'is_active': forms.CheckboxInput(),
            'photo_class': forms.TextInput(attrs={'class': 'dash-input', 'placeholder': 'e.g. photo--tile'}),
            'order': forms.NumberInput(attrs={'class': 'dash-input', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.price_pence:
                self.fields['price'].initial = Decimal(self.instance.price_pence) / 100
            if self.instance.shipping_override_pence is not None:
                self.fields['shipping'].initial = Decimal(self.instance.shipping_override_pence) / 100

    def save(self, commit=True):
        instance = super().save(commit=False)
        price = self.cleaned_data.get('price')
        if price is not None:
            instance.price_pence = int(price * 100)
        shipping = self.cleaned_data.get('shipping')
        instance.shipping_override_pence = int(shipping * 100) if shipping is not None else None
        if commit:
            instance.save()
        return instance

from apps.booking.models import Package
from decimal import Decimal

class PackageForm(forms.ModelForm):
    price = forms.DecimalField(
        label="Price (£)",
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=8,
        widget=forms.NumberInput(attrs={
            'class': 'dash-input',
            'step': '0.01',
            'placeholder': '0.00',
            'min': '0',
        }),
    )

    class Meta:
        model = Package
        fields = ['name', 'session_type', 'location', 'session_count', 'valid_days', 'is_active', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'dash-input'}),
            'session_type': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'location': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'session_count': forms.NumberInput(attrs={'class': 'dash-input', 'min': '1'}),
            'valid_days': forms.NumberInput(attrs={'class': 'dash-input', 'min': '1'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'dash-checkbox'}),
            'order': forms.NumberInput(attrs={'class': 'dash-input', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.price_pence:
            self.fields['price'].initial = Decimal(self.instance.price_pence) / 100

    def save(self, commit=True):
        instance = super().save(commit=False)
        price = self.cleaned_data.get('price')
        if price is not None:
            instance.price_pence = int(price * 100)
        if commit:
            instance.save()
        return instance


from apps.booking.models import Booking

class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = [
            'session_type', 'location', 'date', 'start_time', 'end_time',
            'client_name', 'client_email', 'client_phone', 'status', 'amount_pence', 'notes'
        ]
        widgets = {
            'session_type': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'location': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'date': forms.DateInput(attrs={'class': 'dash-input', 'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'class': 'dash-input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'dash-input', 'type': 'time'}),
            'client_name': forms.TextInput(attrs={'class': 'dash-input'}),
            'client_email': forms.EmailInput(attrs={'class': 'dash-input'}),
            'client_phone': forms.TextInput(attrs={'class': 'dash-input'}),
            'status': forms.Select(attrs={'class': 'dash-input dash-input--select'}),
            'amount_pence': forms.NumberInput(attrs={'class': 'dash-input'}),
            'notes': forms.Textarea(attrs={'class': 'dash-textarea', 'rows': 3}),
        }

