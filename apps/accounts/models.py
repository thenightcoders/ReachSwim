"""
Custom User model — email as the login field, role-based access.

Roles:
  owner  — business owner (Maren). Full dashboard access.
  staff  — future coaches/assistants. Limited dashboard access.
  client — swimmers. Can view their own bookings + profile.
"""
import secrets
from datetime import timedelta

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
    def can_access_dashboard(self):
        """Owner and staff can access the dashboard."""
        return self.role in (self.ROLE_OWNER, self.ROLE_STAFF)


class MagicLinkToken(models.Model):
    """
    Single-use time-limited token for passwordless email login.

    On creation any previous unused tokens for that user are deleted —
    only one pending link at a time.
    """

    EXPIRY_MINUTES = 15

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="magic_tokens",
    )
    token = models.CharField(max_length=43, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"MagicLink({self.user.email}, used={self.used})"

    @property
    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=self.EXPIRY_MINUTES)

    @classmethod
    def create_for_user(cls, user):
        """Invalidate old pending tokens, issue a fresh one."""
        cls.objects.filter(user=user, used=False).delete()
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(32),  # 43 chars, 256 bits — more than enough
        )


class WebAuthnCredential(models.Model):
    """
    A stored passkey credential for a user.
    One user can have multiple credentials (phone, laptop, hardware key).
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="passkeys",
    )
    # Raw credential bytes from the authenticator — stored as BinaryField
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveIntegerField(default=0)
    # AAGUID identifies the authenticator model (optional, informational)
    aaguid = models.CharField(max_length=36, blank=True)
    # Human-readable label the user can set ("iPhone", "YubiKey", etc.)
    name = models.CharField(max_length=100, default="Passkey")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} — {self.name}"
