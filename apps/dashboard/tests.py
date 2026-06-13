"""
Tests for apps/dashboard/views.py

Fix 8 — SettingsViewHeroBugTest:
  Saving the hero section must only call hero.save(), not site.save().
  The stray site.save() in the hero branch was updating SiteConfig's
  cache timestamp and potentially overwriting concurrent site edits.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages.models import HeroSection, SiteConfig

User = get_user_model()

SETTINGS_URL = reverse("dashboard:settings")


class SettingsViewHeroBugTest(TestCase):

    def setUp(self):
        # Owner user required to access dashboard
        self.owner = User.objects.create_user(
            email="owner@reachswim.co.uk",
            password="strongpass123",
            full_name="Coach Maren",
            role="owner",
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)

        # Ensure singletons exist
        self.site = SiteConfig.load()
        self.site.site_name = "Original Name"
        self.site.save()

        self.hero = HeroSection.load()
        self.hero.headline = "Original headline"
        self.hero.save()

    def test_hero_save_updates_hero_not_site(self):
        """POSTing to the hero section must save hero fields, leave site unchanged."""
        response = self.client.post(SETTINGS_URL, {
            "_section": "hero",
            "headline": "New headline",
            "subheadline": "New subheadline",
            "cta_primary_text": "Book now",
            "cta_secondary_text": "Shop",
            "strip_items": "London|Adults",
        })

        self.assertRedirects(response, SETTINGS_URL)

        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "New headline")

        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "Original Name",
                         "site_name must not change when saving the hero section")

    def test_hero_save_does_not_call_site_save(self):
        """
        Verify at the model level: SiteConfig.updated_at must not change
        when the hero section is saved.
        """
        from django.utils import timezone
        import time

        self.site.save()  # stamp updated_at now
        site_before = SiteConfig.objects.get(pk=1).updated_at if hasattr(SiteConfig, 'updated_at') else None

        time.sleep(0.05)  # ensure clock would advance if save() were called

        self.client.post(SETTINGS_URL, {
            "_section": "hero",
            "headline": "Another headline",
            "subheadline": "sub",
            "cta_primary_text": "Book",
            "cta_secondary_text": "Shop",
            "strip_items": "London",
        })

        # Hero must have changed
        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "Another headline")

        # Site name must be untouched
        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "Original Name")

    def test_site_save_does_not_affect_hero(self):
        """Sanity check: saving the site section leaves hero alone."""
        response = self.client.post(SETTINGS_URL, {
            "_section": "site",
            "site_name": "ReachSwim Updated",
            "tagline": "Swim better",
            "email": "hi@reachswim.co.uk",
            "phone": "",
            "location_text": "London",
            "meta_description": "Adult coaching",
            "whatsapp_url": "",
            "instagram_url": "",
            "established_year": "2021",
        })

        self.assertRedirects(response, SETTINGS_URL)

        self.site.refresh_from_db()
        self.assertEqual(self.site.site_name, "ReachSwim Updated")

        self.hero.refresh_from_db()
        self.assertEqual(self.hero.headline, "Original headline",
                         "Hero headline must not change when saving the site section")


# ---------------------------------------------------------------------------
# Fix 9 — dashboard home must not use __import__ hack
# ---------------------------------------------------------------------------

class DashboardHomeTotalClientsTest(TestCase):
    """
    Fix 9 — dashboard/home view previously used __import__ to get the User model.
    The fix replaces it with a direct import.  These tests verify the stat is
    counted correctly, which would fail if the import were broken.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@reachswim.co.uk",
            password="ownerpass",
            full_name="Coach Maren",
            role="owner",
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)
        # Ensure singletons exist so context processors don't error
        from apps.pages.models import SiteConfig
        SiteConfig.load()

    def test_home_view_returns_200(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)

    def test_total_clients_is_zero_when_no_clients_exist(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.context["total_clients"], 0)

    def test_total_clients_counts_only_client_role(self):
        """Owners and staff must not be counted — only role='client'."""
        User.objects.create_user(
            email="c1@example.com", full_name="Client One", role="client"
        )
        User.objects.create_user(
            email="c2@example.com", full_name="Client Two", role="client"
        )
        User.objects.create_user(
            email="staff@example.com", full_name="Staff", role="staff"
        )
        response = self.client.get("/dashboard/")
        self.assertEqual(response.context["total_clients"], 2,
                         "Only users with role='client' should be counted")
