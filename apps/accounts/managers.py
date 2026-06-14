"""
Custom user manager — email is the unique identifier, no username.
"""
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """Manager for the custom User model that uses email as the login field."""

    def _create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        # Strip whitespace before normalization — without this, ' user@example.com '
        # registers successfully (unique constraint passes) but can never be logged
        # into because login strips and the stored value doesn't match.
        email = self.normalize_email(email.strip())
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "owner")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)
