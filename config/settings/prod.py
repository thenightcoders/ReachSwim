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
