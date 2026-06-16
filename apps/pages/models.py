from django.db import models


class SingletonModel(models.Model):
    """
    Base for models that should only have one instance (pk=1 always).
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # prevent deletion

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# =============================================================================
# Site Configuration (global settings)
# =============================================================================

class SiteConfig(SingletonModel):
    """Global site settings — editable in admin."""

    CURRENCY_CHOICES = [
        ("GBP", "British Pound (£)"),
        ("EUR", "Euro (€)"),
        ("USD", "US Dollar ($)"),
    ]
    CURRENCY_SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}

    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default="GBP",
        help_text=(
            "Currency symbol shown in the dashboard and templates. "
            "DISPLAY ONLY — changing this does not affect Stripe (hardcoded to GBP), "
            "model price_display properties (hardcoded to £), or any pricing logic. "
            "To support multiple real currencies, update all price_pence fields, "
            "the pence_to_pounds template filter, and the Stripe session currency."
        ),
    )

    site_name = models.CharField(max_length=100, default="ReachSwim")
    tagline = models.CharField(max_length=200, default="Adult swim coaching")
    logo = models.ImageField(upload_to="site/", blank=True)
    favicon = models.ImageField(upload_to="site/", blank=True)

    # Contact
    email = models.EmailField(default="hi@reachswim.co.uk")
    phone = models.CharField(max_length=30, blank=True)

    # Social media URLs
    whatsapp_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)
    snapchat_url = models.URLField(blank=True)

    # Location headline
    location_text = models.CharField(max_length=100, default="London")
    established_year = models.PositiveIntegerField(default=2021)

    # SEO
    meta_description = models.TextField(
        max_length=300,
        default="Adult swim coaching in London. One coach, your lane, real progress.",
    )

    @property
    def currency_symbol(self) -> str:
        return self.CURRENCY_SYMBOLS.get(self.currency, "£")

    class Meta:
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

    def __str__(self):
        return "Site Configuration"


# =============================================================================
# Hero Section
# =============================================================================

class HeroSection(SingletonModel):
    """Homepage hero — one instance, admin-editable."""

    headline = models.CharField(max_length=200, default="Make peace with the pool.")
    headline_accent = models.CharField(
        max_length=50, default="pool.",
        help_text="Word(s) to italicize/accent in headline",
    )
    subheadline = models.TextField(
        max_length=500,
        default="One-on-one and small-group coaching for adults in London — every shape, speed, and story. From your first lap to your fastest.",
    )
    background_image = models.ImageField(upload_to="hero/", blank=True)
    cta_primary_text = models.CharField(max_length=50, default="Book a session")
    cta_secondary_text = models.CharField(max_length=50, default="Browse caps & goggles")

    # Bottom strip items
    strip_items = models.TextField(
        default="London|Adult sessions|1:1 · Small group · Packages|★★★★★ 412 reviews",
        help_text="Pipe-separated items for the bottom marquee strip",
    )

    class Meta:
        verbose_name = "Hero Section"
        verbose_name_plural = "Hero Section"

    def __str__(self):
        return "Hero Section"

    @property
    def strip_items_list(self):
        return [s.strip() for s in self.strip_items.split("|") if s.strip()]


# =============================================================================
# Offerings
# =============================================================================

class Offering(models.Model):
    """Service offering card (1:1, Small group, Packages, etc.)."""

    tag = models.CharField(max_length=50, help_text="e.g. '01 — Private'")
    title = models.CharField(max_length=100)
    description = models.TextField()
    meta_items = models.CharField(
        max_length=200,
        help_text="Comma-separated meta badges, e.g. '60 min, East London, From £80'",
    )
    photo_class = models.CharField(
        max_length=50, default="photo--surface",
        help_text="CSS class for the gradient placeholder photo",
    )
    photo_label = models.CharField(max_length=100, blank=True)
    image = models.ImageField(upload_to="offerings/", blank=True, help_text="Optional real image (overrides gradient)")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "Offering"

    def __str__(self):
        return self.title

    @property
    def meta_list(self):
        return [m.strip() for m in self.meta_items.split(",") if m.strip()]


# =============================================================================
# Approach Section
# =============================================================================

class ApproachSection(SingletonModel):
    """The 'Our Approach' editorial section — text content."""

    kicker = models.CharField(max_length=50, default="Our approach")
    headline = models.CharField(max_length=200, default="We treat the water like a craft, not a chore.")
    headline_accent = models.CharField(max_length=100, default="like a craft,")
    body = models.TextField(
        default="ReachSwim started in 2021 in one borrowed lane in east London. "
        "Five years later, it's still one coach and one pool — but two thousand "
        "adults have gone from water-shy to confident swimmers.",
    )

    class Meta:
        verbose_name = "Approach Section"
        verbose_name_plural = "Approach Section"

    def __str__(self):
        return "Approach Section"


class Stat(models.Model):
    """Stats displayed in the approach section."""

    value = models.CharField(max_length=20, help_text="e.g. '2,140+'")
    label = models.CharField(max_length=50, help_text="e.g. 'Adults coached'")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.value} — {self.label}"


class ApproachPillar(models.Model):
    """Numbered pillars in the approach section."""

    number = models.CharField(max_length=5, help_text="e.g. '01'")
    title = models.CharField(max_length=100)
    description = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "Approach Pillar"

    def __str__(self):
        return f"{self.number}. {self.title}"


# =============================================================================
# Testimonials
# =============================================================================

class Testimonial(models.Model):
    """Client testimonial quote."""

    quote = models.TextField()
    author_name = models.CharField(max_length=100)
    author_role = models.CharField(max_length=150, help_text="e.g. 'Software engineer · Hackney'")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.author_name}: \"{self.quote[:40]}...\""


# =============================================================================
# FAQ
# =============================================================================

class FAQItem(models.Model):
    """Frequently asked question."""

    question = models.CharField(max_length=300)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "FAQ Item"

    def __str__(self):
        return self.question


# =============================================================================
# Footer
# =============================================================================

class FooterColumn(models.Model):
    """Footer navigation column."""

    title = models.CharField(max_length=50)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "Footer Column"

    def __str__(self):
        return self.title


class FooterLink(models.Model):
    """Link within a footer column."""

    column = models.ForeignKey(FooterColumn, on_delete=models.CASCADE, related_name="links")
    label = models.CharField(max_length=50)
    url = models.CharField(max_length=200, default="#")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "Footer Link"

    def __str__(self):
        return self.label
