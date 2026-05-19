"""
Custom User model — email as the login field, role-based access.

Roles:
  owner  — business owner (Maren). Full dashboard access.
  staff  — future coaches/assistants. Limited dashboard access.
  client — swimmers. Can view their own bookings + profile.
"""
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user — email login, no username."""

    ROLE_OWNER = "owner"
    ROLE_STAFF = "staff"
    ROLE_CLIENT = "client"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_STAFF, "Staff"),
        (ROLE_CLIENT, "Client"),
    ]

    email = models.EmailField(
        unique=True,
        error_messages={"unique": "A user with that email already exists."},
    )
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_CLIENT,
        db_index=True,
    )

    # Django auth plumbing
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Grants access to the Django admin (dev use only).",
    )
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]  # prompted by createsuperuser

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    @property
    def first_name(self):
        """Convenience — return everything before the first space."""
        return self.full_name.split()[0] if self.full_name else ""

    @property
    def is_owner(self):
        return self.role == self.ROLE_OWNER

    @property
    def is_client(self):
        return self.role == self.ROLE_CLIENT

    @property
    def can_access_dashboard(self):
        """Owner and staff can access the dashboard."""
        return self.role in (self.ROLE_OWNER, self.ROLE_STAFF)
