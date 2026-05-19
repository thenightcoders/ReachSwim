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


class ContactMessage(models.Model):
    """Stores submitted contact form messages."""

    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Contact Message"

    def __str__(self):
        return f"{self.name} — {self.subject or '(no subject)'}"
