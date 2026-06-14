"""
Production settings for ReachSwim.
Uses: DJANGO_SETTINGS_MODULE=config.settings.prod
"""
import os
from .base import *  # noqa: F401, F403

# Send real emails via SMTP
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

SITE_URL = os.getenv("SITE_URL", "https://reachswim.co.uk").rstrip("/")

# HTTPS / security hardening
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

_csrf_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Cache — Redis (shared across all gunicorn workers)
# ---------------------------------------------------------------------------
# The default in-memory cache (LocMemCache) is per-process, so a
# SingletonModel.save() on worker A won't bust worker B's cached object.
# Redis gives all workers a single shared cache, fixing this.
# Requires: pip install django-redis  OR  Django 4.0+ built-in Redis backend.
# Env var: REDIS_URL (e.g. redis://localhost:6379/0)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    }
}
