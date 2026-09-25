"""
Production settings for ReachSwim.
Uses: DJANGO_SETTINGS_MODULE=config.settings.prod
"""
import os
from .base import *  # noqa: F401, F403

# Send real emails via SMTP
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

SITE_URL = os.getenv("SITE_URL", "https://reachswim.co.uk").rstrip("/")

# HTTPS hardening lives in base.py (applied whenever DEBUG is off).

_csrf_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# TODO: add Redis cache when traffic warrants it — wire up SingletonModel
# caching (cache.get/set with 5 min TTL, busted on save) and point CACHES
# at redis://... via env var. Rate limiter (payments/services/rate_limiter.py)
# will also benefit from a shared cache across gunicorn workers.
