"""
Authentication forms — login, registration, profile editing.
"""
from django import forms
from django.contrib.auth import authenticate

from .models import User


class LoginForm(forms.Form):
    """Email + password login."""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Email address",
            "class": "form-input",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "form-input",
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user_cache = None

    def clean(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        password = self.cleaned_data.get("password", "")

        if email and password:
            self.user_cache = authenticate(
                self.request, username=email, password=password,
            )
            if self.user_cache is None:
                raise forms.ValidationError("Invalid email or password.")
            if not self.user_cache.is_active:
                raise forms.ValidationError("This account is disabled.")

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class RegisterForm(forms.ModelForm):
    """Client registration — email + name + phone + password."""

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "form-input",
        }),
        min_length=8,
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Confirm password",
            "class": "form-input",
        }),
        label="Confirm password",
    )

    class Meta:
        model = User
        fields = ("email", "full_name", "phone")
        widgets = {
            "email": forms.EmailInput(attrs={
                "placeholder": "Email address",
                "class": "form-input",
                "autofocus": True,
            }),
            "full_name": forms.TextInput(attrs={
                "placeholder": "Full name",
                "class": "form-input",
            }),
            "phone": forms.TextInput(attrs={
                "placeholder": "Phone (optional)",
                "class": "form-input",
            }),
        }

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw2 = cleaned.get("password_confirm")
        if pw and pw2 and pw != pw2:
            self.add_error("password_confirm", "Passwords don't match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.role = User.ROLE_CLIENT
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """Edit profile — name + phone. Email is read-only (shown but not editable)."""

    class Meta:
        model = User
        fields = ("full_name", "phone")
        widgets = {
            "full_name": forms.TextInput(attrs={
                "class": "form-input",
            }),
            "phone": forms.TextInput(attrs={
                "placeholder": "Phone (optional)",
                "class": "form-input",
            }),
        }
