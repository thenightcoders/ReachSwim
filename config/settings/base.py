"""
Base settings for ReachSwim project.
Shared by all environments. Do not put environment-specific overrides here.
"""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# config/settings/base.py → config/settings → config → project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
secret_key_value = os.getenv("SECRET_KEY_VALUE")
if not secret_key_value:
    raise ImproperlyConfigured("SECRET_KEY_VALUE environment variable is not set")

SECRET_KEY = secret_key_value
DEBUG = os.getenv("DEBUG_VALUE", "False").strip().lower() == "true"

_allowed_hosts_str = os.getenv("LIST_OF_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = ["*"] if DEBUG else [h.strip() for h in _allowed_hosts_str.split(",") if h.strip()]

# ---------------------------------------------------------------------------
# Site / admin
# ---------------------------------------------------------------------------
SITE_ID = 1
SITE_NAME = os.getenv("SITE_NAME", "ReachSwim")
SITE_DESCRIPTION = os.getenv("SITE_DESCRIPTION", "Adult swim coaching in London")
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").strip().lower() == "true"

ADMIN_NAME = os.getenv("ADMIN_NAME", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
ADMINS = [(ADMIN_NAME, ADMIN_EMAIL)] if ADMIN_EMAIL else []
MANAGERS = ADMINS

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local
    "apps.accounts",
    "apps.booking",
    "apps.legal",
    "apps.pages",
    "apps.payments",
    "apps.shop",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# URLs / WSGI
# ---------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = True

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.pages.context_processors.site_context",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---------------------------------------------------------------------------
# Auth / passwords
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Sessions & messages
# ---------------------------------------------------------------------------
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---------------------------------------------------------------------------
# Email  (overridden per-environment)
# ---------------------------------------------------------------------------
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = EMAIL_PORT != 465
EMAIL_USE_SSL = EMAIL_PORT == 465
EMAIL_SUBJECT_PREFIX = ""
EMAIL_USE_LOCALTIME = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# ---------------------------------------------------------------------------
# i18n / timezone
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_URL = os.getenv("SITE_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_level = "DEBUG" if DEBUG else "INFO"
_handlers = ["console"] if DEBUG else ["console", "file"]

logs_dir = BASE_DIR / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if DEBUG else "simple",
            "level": _log_level,
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": logs_dir / "django.log",
            "formatter": "verbose",
            "level": "INFO",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": _handlers, "level": "INFO", "propagate": False},
        "django.core.mail": {"handlers": ["console"], "level": _log_level, "propagate": False},
        "apps.booking": {"handlers": _handlers, "level": _log_level, "propagate": False},
    },
}

