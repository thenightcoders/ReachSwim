"""
Development settings for ReachSwim.
Uses: DJANGO_SETTINGS_MODULE=config.settings.dev
"""
import os
from .base import *  # noqa: F401, F403

# Print emails to the console instead of sending them
#EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

SITE_URL = "http://127.0.0.1:8000"

# Allow OAuth2 over plain HTTP on localhost (never set this in production)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# Serve static/ directly with runserver. STATIC_ROOT is unset here because
# Django refuses STATICFILES_DIRS containing STATIC_ROOT (staticfiles.E002);
# collectstatic in production still targets static/ via base.py.
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
STATIC_ROOT = None
