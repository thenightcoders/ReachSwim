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

