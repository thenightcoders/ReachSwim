import uuid
from django.db import models
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from apps.pages.models import SingletonModel


# =============================================================================
# Booking Configuration (singleton)
# =============================================================================

class BookingSettings(SingletonModel):
    """Global booking behaviour — one row, always pk=1."""

    max_advance_days = models.PositiveIntegerField(
        default=30,
        help_text="How many days ahead clients can book.",
    )
    min_advance_hours = models.PositiveIntegerField(
        default=2,
        help_text="Minimum hours before a session starts that it can be booked.",
    )
    cancellation_hours = models.PositiveIntegerField(
        default=12,
        help_text="Free cancellation window (hours before session).",
    )
    slot_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Default session length in minutes.",
    )
    booking_page_heading = models.CharField(
        max_length=200,
        default="Book a session",
    )
    booking_page_subheading = models.TextField(
        blank=True,
        default="Pick your session, choose a time, and you're in the water.",
    )

    class Meta:
        verbose_name = "Booking settings"
        verbose_name_plural = "Booking settings"

    def __str__(self):
        return "Booking settings"


# =============================================================================
# Session types
# =============================================================================

class SessionType(models.Model):
    """A kind of swimming session the coach offers."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    max_participants = models.PositiveIntegerField(
        default=1,
        help_text="1 for private, higher for group classes.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


# =============================================================================
# Locations
# =============================================================================

class Location(models.Model):
    """A swimming pool / venue where sessions take place."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    address = models.TextField()
    description = models.TextField(blank=True)
    has_parking = models.BooleanField(default=False)
    has_hoist = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


# =============================================================================
# Pricing  (session type + location = price)
# =============================================================================

class SessionPricing(models.Model):
    """
    Price for a given session type at a given location.
    Stored in pence to avoid float rounding.
    """

    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="pricing",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="pricing",
    )
    price_pence = models.PositiveIntegerField(
        help_text="Price in pence (e.g. 4500 = £45.00).",
    )

    class Meta:
        unique_together = ("session_type", "location")
        verbose_name = "Session pricing"
        verbose_name_plural = "Session pricing"

    def __str__(self):
        return f"{self.session_type} @ {self.location} — {self.price_display}"

    @property
    def price_display(self):
        pounds = self.price_pence / 100
        return f"£{pounds:.2f}"


# =============================================================================
# Packages  (buy N sessions at a discount)
# =============================================================================

class Package(models.Model):
    """Multi-session bundle at a reduced rate."""

    name = models.CharField(max_length=200)
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="packages",
    )
    session_count = models.PositiveIntegerField(
        help_text="Number of sessions in this package.",
    )
    price_pence = models.PositiveIntegerField(
        help_text="Total package price in pence.",
    )
    valid_days = models.PositiveIntegerField(
        default=365,
        help_text="Days from purchase until the package expires.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def price_display(self):
        pounds = self.price_pence / 100
        return f"£{pounds:.2f}"

    @property
    def per_session_pence(self):
        if self.session_count:
            return self.price_pence // self.session_count
        return 0

    @property
    def per_session_display(self):
        pounds = self.per_session_pence / 100
        return f"£{pounds:.2f}"


# =============================================================================
# Recurring schedule  (weekly class timetable)
# =============================================================================

DAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class RecurringSchedule(models.Model):
    """
    A weekly recurring slot.  The availability service expands these
    into concrete date+time slots for any requested date range.
    """

    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    max_capacity = models.PositiveIntegerField(
        default=1,
        help_text="How many clients can attend this slot.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["day_of_week", "start_time"]
        verbose_name = "Recurring schedule"
        verbose_name_plural = "Recurring schedules"

    def __str__(self):
        day = dict(DAY_CHOICES).get(self.day_of_week, "?")
        return (
            f"{self.session_type} — {day} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M} "
            f"@ {self.location}"
        )


# =============================================================================
# Google Calendar integration
# =============================================================================

class GoogleCalendarConfig(SingletonModel):
    """
    OAuth credentials for the owner's Google Calendar.

    Security note: client_secret and credentials_json contain sensitive
    credentials.  In production, prefer the env var overrides below so
    these values never touch the database:

        GOOGLE_CALENDAR_CLIENT_ID=...
        GOOGLE_CALENDAR_CLIENT_SECRET=...
        GOOGLE_CALENDAR_CREDENTIALS_JSON=...  (full JSON token string)

    The effective_* properties read env vars first and fall back to the DB
    fields, so existing setups (configured via admin) keep working without
    any change.
    """

    client_id = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "OAuth2 Client ID from Google Cloud Console. "
            "Override with GOOGLE_CALENDAR_CLIENT_ID env var in production."
        ),
    )
    client_secret = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "OAuth2 Client Secret from Google Cloud Console. "
            "Override with GOOGLE_CALENDAR_CLIENT_SECRET env var in production "
            "to keep secrets out of the database."
        ),
    )
    calendar_id = models.CharField(
        max_length=255,
        blank=True,
        default="primary",
        help_text="Google Calendar ID — leave as 'primary' to use the main calendar.",
    )
    credentials_json = models.TextField(
        blank=True,
        help_text=(
            "Stored OAuth2 tokens (set automatically after connecting). "
            "Override with GOOGLE_CALENDAR_CREDENTIALS_JSON env var to keep "
            "OAuth refresh tokens out of the database."
        ),
    )
    is_connected = models.BooleanField(default=False)
    last_synced = models.DateTimeField(null=True, blank=True)
    sync_deletions_from_calendar = models.BooleanField(
        default=False,
        help_text=(
            "When enabled: if you delete a booking event from Google Calendar, "
            "the matching booking on the website is automatically cancelled."
        ),
    )

    class Meta:
        verbose_name = "Google Calendar"
        verbose_name_plural = "Google Calendar"

    def __str__(self):
        if self.is_connected:
            return f"Connected — {self.calendar_id}"
        return "Not connected"

    # ------------------------------------------------------------------
    # Env var overrides — use these everywhere instead of the raw fields
    # ------------------------------------------------------------------

    @property
    def effective_client_id(self) -> str:
        """Env var GOOGLE_CALENDAR_CLIENT_ID takes precedence over DB field."""
        import os
        return os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or self.client_id

    @property
    def effective_client_secret(self) -> str:
        """Env var GOOGLE_CALENDAR_CLIENT_SECRET takes precedence over DB field."""
        import os
        return os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET") or self.client_secret

    @property
    def effective_credentials_json(self) -> str:
        """Env var GOOGLE_CALENDAR_CREDENTIALS_JSON takes precedence over DB field."""
        import os
        return os.getenv("GOOGLE_CALENDAR_CREDENTIALS_JSON") or self.credentials_json


# =============================================================================
# Bookings
# =============================================================================

class Booking(models.Model):
    """
    A single reserved session slot.
    Status tracks the lifecycle: pending → confirmed → completed / cancelled.
    """

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending payment"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_COMPLETED, "Completed"),
    ]

    # Unique reference for URLs and Stripe metadata
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # What & where
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    # When
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    # Who — string fields are the authoritative audit record.
    # user is an optional link to the accounts.User who booked;
    # null when the booking was made by a guest (no account at checkout time).
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=30, blank=True)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
        help_text=(
            "Linked account if the client was authenticated at checkout. "
            "Null for guest bookings. "
            "client_email remains the authoritative audit record regardless."
        ),
    )

    # Status & payment
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    amount_pence = models.PositiveIntegerField(default=0)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)

    # Google Calendar event
    google_event_id = models.CharField(max_length=255, blank=True)

    # Cancellation
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    # Refund
    is_refunded = models.BooleanField(default=False)
    refunded_amount_pence = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Coach notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["date", "status"]),
            models.Index(fields=["client_email"]),
        ]

    def __str__(self):
        return (
            f"{self.session_type} — {self.date} "
            f"{self.start_time:%H:%M} ({self.get_status_display()})"
        )

    @property
    def amount_display(self):
        pounds = self.amount_pence / 100
        return f"£{pounds:.2f}"

    @classmethod
    def with_spots_taken(cls):
        """
        Return a queryset with each booking annotated with `spots_taken_count`
        — the number of non-cancelled bookings sharing the same slot.
        One correlated subquery per row instead of N individual COUNT queries.
        """
        taken = (
            cls.objects
            .filter(
                session_type_id=OuterRef("session_type_id"),
                location_id=OuterRef("location_id"),
                date=OuterRef("date"),
                start_time=OuterRef("start_time"),
            )
            .exclude(status=cls.STATUS_CANCELLED)
            .values("session_type_id")  # collapse to one group
            .annotate(cnt=Count("pk"))
            .values("cnt")
        )
        return cls.objects.annotate(spots_taken_count=Subquery(taken))

    @classmethod
    def count_for_slot(
        cls,
        session_type_id: int,
        location_id: int,
        date,
        start_time,
    ) -> int:
        """Count non-cancelled bookings for a given (session_type, location, date, time) tuple.

        Single authoritative implementation — used by spots_taken and the
        availability service so the query logic lives in exactly one place.
        """
        return (
            cls.objects
            .filter(
                session_type_id=session_type_id,
                location_id=location_id,
                date=date,
                start_time=start_time,
            )
            .exclude(status=cls.STATUS_CANCELLED)
            .count()
        )

    @property
    def spots_taken(self):
        """
        How many non-cancelled bookings exist for the same slot.
        If the queryset was built with with_spots_taken(), reads the annotation
        from __dict__ (zero extra queries).  Falls back to count_for_slot otherwise.
        """
        if "spots_taken_count" in self.__dict__:
            return self.__dict__["spots_taken_count"]
        return Booking.count_for_slot(
            self.session_type_id,
            self.location_id,
            self.date,
            self.start_time,
        )
