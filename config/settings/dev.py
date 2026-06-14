"""
Development settings for ReachSwim.
Uses: DJANGO_SETTINGS_MODULE=config.settings.dev
"""
import os
from .base import *  # noqa: F401, F403

# Print emails to the console instead of sending them
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SITE_URL = "http://127.0.0.1:8000"

# Allow OAuth2 over plain HTTP on localhost (never set this in production)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
