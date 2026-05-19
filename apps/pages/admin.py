from django.contrib import admin
from .models import (
    SiteConfig,
    HeroSection,
    Offering,
    ApproachSection,
    Stat,
    ApproachPillar,
    Testimonial,
    FAQItem,
    FooterColumn,
    FooterLink,
)


# =============================================================================
# Singleton admin mixin
# =============================================================================

class SingletonAdmin(admin.ModelAdmin):
    """Admin for singleton models — no add, no delete, auto-redirect to instance."""

    def has_add_permission(self, request):
        return not self.model.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = self.model.load()
        from django.urls import reverse
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
        from django.shortcuts import redirect
        return redirect(url)


# =============================================================================
# Site Config
# =============================================================================

@admin.register(SiteConfig)
class SiteConfigAdmin(SingletonAdmin):
    fieldsets = (
        ("Brand", {"fields": ("site_name", "tagline", "logo", "favicon")}),
        ("Contact", {"fields": ("email", "phone", "whatsapp_url", "instagram_url")}),
        ("Location", {"fields": ("location_text", "established_year")}),
        ("SEO", {"fields": ("meta_description",)}),
    )


# =============================================================================
# Hero
# =============================================================================

@admin.register(HeroSection)
class HeroSectionAdmin(SingletonAdmin):
    fieldsets = (
        ("Content", {"fields": ("headline", "headline_accent", "subheadline")}),
        ("Media", {"fields": ("background_image",)}),
        ("Calls to Action", {"fields": ("cta_primary_text", "cta_secondary_text")}),
        ("Bottom Strip", {"fields": ("strip_items",)}),
    )


# =============================================================================
# Offerings
# =============================================================================

@admin.register(Offering)
class OfferingAdmin(admin.ModelAdmin):
    list_display = ("tag", "title", "order")
    list_editable = ("order",)
    fieldsets = (
        (None, {"fields": ("tag", "title", "description", "meta_items")}),
        ("Visual", {"fields": ("photo_class", "photo_label", "image")}),
        ("Order", {"fields": ("order",)}),
    )


# =============================================================================
# Approach
# =============================================================================

@admin.register(ApproachSection)
class ApproachSectionAdmin(SingletonAdmin):
    fieldsets = (
        (None, {"fields": ("kicker", "headline", "headline_accent", "body")}),
    )


@admin.register(Stat)
class StatAdmin(admin.ModelAdmin):
    list_display = ("value", "label", "order")
    list_editable = ("order",)


@admin.register(ApproachPillar)
class ApproachPillarAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "order")
    list_editable = ("order",)


# =============================================================================
# Testimonials
# =============================================================================

@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author_name", "quote_preview", "is_active", "order")
    list_editable = ("is_active", "order")
    list_filter = ("is_active",)

    @admin.display(description="Quote")
    def quote_preview(self, obj):
        return obj.quote[:60] + "..." if len(obj.quote) > 60 else obj.quote


# =============================================================================
# FAQ
# =============================================================================

@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ("question", "is_active", "order")
    list_editable = ("is_active", "order")
    list_filter = ("is_active",)


# =============================================================================
# Footer
# =============================================================================

class FooterLinkInline(admin.TabularInline):
    model = FooterLink
    extra = 1
    fields = ("label", "url", "order")


@admin.register(FooterColumn)
class FooterColumnAdmin(admin.ModelAdmin):
    list_display = ("title", "order")
    list_editable = ("order",)
    inlines = [FooterLinkInline]
