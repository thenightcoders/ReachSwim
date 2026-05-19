"""
Development settings for ReachSwim.
Uses: DJANGO_SETTINGS_MODULE=config.settings.dev
"""
from .base import *  # noqa: F401, F403

# Print emails to the console instead of sending them
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SITE_URL = "http://127.0.0.1:8000"
