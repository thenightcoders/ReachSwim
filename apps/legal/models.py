from django.db import models
from apps.pages.models import SingletonModel


class LegalPage(models.Model):
    """Admin-editable legal/policy page (privacy, terms, accessibility, etc.)."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, help_text="URL slug, e.g. 'privacy-policy'")
    content = models.TextField(help_text="Page body. HTML is allowed.")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "Legal Page"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("legal:page", kwargs={"slug": self.slug})


class ContactConfig(SingletonModel):
    """Contact page settings — singleton, admin-editable."""

    heading = models.CharField(max_length=200, default="Get in touch")
    subheading = models.TextField(
        max_length=500,
        default="Questions, feedback, or just want to say hello — we read every message.",
    )
    email = models.EmailField(default="hi@reachswim.co.uk")
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True, help_text="Physical address if applicable")
    success_message = models.CharField(
        max_length=300,
        default="Thanks for reaching out. We'll get back to you within 24 hours.",
    )

    class Meta:
        verbose_name = "Contact Settings"
        verbose_name_plural = "Contact Settings"

    def __str__(self):
        return "Contact Settings"


class ContactMessageQuerySet(models.QuerySet):
    """A message sits in exactly one folder: inbox, quarantine or spam."""

    def inbox(self):
        return self.filter(is_spam=False, quarantined=False)

    def quarantine(self):
        return self.filter(is_spam=False, quarantined=True)

    def spam(self):
        return self.filter(is_spam=True)

    def from_email(self, email):
        return self.filter(email__iexact=email.strip())


class ContactMessage(models.Model):
    """Stores submitted contact form messages."""

    SPAM_REASONS = [
        ("detector", "Spam detector"),
        ("links", "Too many links"),
        ("banned", "Banned sender"),
        ("owner", "Marked by you"),
    ]

    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    is_spam = models.BooleanField(default=False, db_index=True)
    # Waiting for the spam detection API. Never set together with is_spam.
    quarantined = models.BooleanField(default=False, db_index=True)
    spam_reason = models.CharField(max_length=20, choices=SPAM_REASONS, blank=True)
    spam_score = models.FloatField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True, help_text="When the spam detection API answered")
    check_attempts = models.PositiveSmallIntegerField(default=0)
    # Thank-you to the sender + heads-up to the owner, sent once it reaches the inbox.
    notified_at = models.DateTimeField(null=True, blank=True)

    objects = ContactMessageQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Contact Message"

    def __str__(self):
        return f"{self.name} — {self.subject or '(no subject)'}"

    @property
    def folder(self):
        if self.is_spam:
            return "spam"
        return "quarantine" if self.quarantined else "inbox"


class BannedSender(models.Model):
    """Messages from these addresses always go to Spam. Stored lowercase."""

    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["email"]
        verbose_name = "Banned Sender"

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @classmethod
    def is_banned(cls, email):
        return cls.objects.filter(email=email.strip().lower()).exists()


class SpamCheckStatus(SingletonModel):
    """What the site last heard from the spam detection API."""

    api_ok = models.BooleanField(null=True, help_text="Unknown until the first check")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    alert_sent_at = models.DateTimeField(null=True, blank=True, help_text="Last 'please check quarantine' email")

    class Meta:
        verbose_name = "Spam Check Status"
        verbose_name_plural = "Spam Check Status"

    def __str__(self):
        return "Spam Check Status"
