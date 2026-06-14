"""
Tests for apps/pages/models.py

Fix 7 — SingletonModelTest:
  - _cache_key() is a plain classmethod (no @property stacking)
  - load() populates the cache on first call
  - load() returns the cached object on subsequent calls (no extra DB hit)
  - save() busts the cache so the next load() re-fetches from DB
  - cart_count is injected into the template context (Fix 4)
"""
from unittest.mock import patch, call

from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings

from apps.pages.models import SingletonModel, SiteConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummySingleton(SingletonModel):
    """
    Minimal concrete SingletonModel for testing the base class behaviour
    without touching real content models.
    We can't define it in the model file (would create a migration), so
    we declare it here and tell Django it lives in the pages app.
    """
    class Meta:
        app_label = "pages"


# ---------------------------------------------------------------------------
# Fix 7: SingletonModel caching
# ---------------------------------------------------------------------------

class SingletonModelCacheKeyTest(TestCase):
    """_cache_key() must be callable as a classmethod — no @property stacking."""

    def test_cache_key_accessible_on_class(self):
        key = SiteConfig._cache_key()
        self.assertEqual(key, "singleton_SiteConfig")

    def test_cache_key_accessible_on_instance(self):
        obj = SiteConfig.load()
        self.assertEqual(obj._cache_key(), "singleton_SiteConfig")

    def test_cache_key_differs_per_subclass(self):
        from apps.pages.models import HeroSection
        self.assertNotEqual(SiteConfig._cache_key(), HeroSection._cache_key())


class SingletonModelLoadTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_load_creates_instance_when_none_exists(self):
        obj = SiteConfig.load()
        self.assertIsNotNone(obj)
        self.assertEqual(obj.pk, 1)

    def test_load_populates_cache(self):
        SiteConfig.load()
        cached = cache.get(SiteConfig._cache_key())
        self.assertIsNotNone(cached, "load() must populate the cache")

    def test_load_returns_cached_object_without_extra_db_query(self):
        """Second load() must not hit the database."""
        SiteConfig.load()  # prime the cache

        with self.assertNumQueries(0):
            obj = SiteConfig.load()

        self.assertEqual(obj.pk, 1)

    def test_save_busts_cache(self):
        obj = SiteConfig.load()
        self.assertIsNotNone(cache.get(SiteConfig._cache_key()))

        obj.site_name = "Updated"
        obj.save()

        self.assertIsNone(
            cache.get(SiteConfig._cache_key()),
            "save() must delete the cache entry",
        )

    def test_load_after_save_re_fetches_from_db(self):
        obj = SiteConfig.load()
        obj.site_name = "NewName"
        obj.save()

        # Cache is busted — next load() should go to DB and return fresh data
        fresh = SiteConfig.load()
        self.assertEqual(fresh.site_name, "NewName")

    def test_delete_is_a_noop(self):
        """SingletonModel.delete() must not remove the row."""
        obj = SiteConfig.load()
        obj.delete()
        self.assertEqual(SiteConfig.objects.filter(pk=1).count(), 1)


# ---------------------------------------------------------------------------
# Fix 4: cart_context registered — cart_count in template context
# ---------------------------------------------------------------------------

class CartContextProcessorTest(TestCase):
    """
    cart_count must be present in every template context now that
    apps.payments.context_processors.cart_context is registered.
    """

    def test_cart_count_in_homepage_context(self):
        from apps.pages.models import SiteConfig
        SiteConfig.load()  # ensure singleton exists so context processor doesn't error
        response = self.client.get("/")
        # The context processor injects cart_count; check it's present and numeric
        self.assertIn("cart_count", response.context)
        self.assertIsInstance(response.context["cart_count"], int)

    def test_cart_count_is_zero_for_empty_cart(self):
        SiteConfig.load()
        response = self.client.get("/")
        self.assertEqual(response.context["cart_count"], 0)
