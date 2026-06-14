"""
Authentication forms — login, registration, profile editing.
"""
from django import forms
from django.contrib.auth import authenticate

from .email_validator import validate_email_address
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
        email = self.cleaned_data["email"].strip().lower()
        result = validate_email_address(email)
        if not result.valid:
            raise forms.ValidationError(result.reason)
        return email

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


class ChangePasswordForm(forms.Form):
    """Change password — requires current password confirmation."""

    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(attrs={"class": "form-input", "autofocus": True}),
    )
    new_password = forms.CharField(
        label="New password",
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
    )
    new_password_confirm = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_current_password(self):
        pw = self.cleaned_data["current_password"]
        if self._user and not self._user.check_password(pw):
            raise forms.ValidationError("Current password is incorrect.")
        return pw

    def clean(self):
        cleaned = super().clean()
        pw1 = cleaned.get("new_password")
        pw2 = cleaned.get("new_password_confirm")
        if pw1 and pw2 and pw1 != pw2:
            self.add_error("new_password_confirm", "Passwords don't match.")
        return cleaned


class ChangeEmailForm(forms.Form):
    """Change email — requires current password confirmation."""

    new_email = forms.EmailField(
        label="New email address",
        widget=forms.EmailInput(attrs={"class": "form-input", "autofocus": True}),
    )
    current_password = forms.CharField(
        label="Current password (to confirm)",
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_new_email(self):
        email = self.cleaned_data["new_email"].strip().lower()
        if self._user and email == self._user.email:
            raise forms.ValidationError("That's already your current email.")
        if User.objects.filter(email__iexact=email).exclude(pk=self._user.pk if self._user else None).exists():
            raise forms.ValidationError("An account with that email already exists.")
        return email

    def clean_current_password(self):
        pw = self.cleaned_data["current_password"]
        if self._user and not self._user.check_password(pw):
            raise forms.ValidationError("Current password is incorrect.")
        return pw
