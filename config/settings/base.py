"""
Base settings for ReachSwim project.
"""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Get environment variables with fallbacks
debug_value = os.getenv('DEBUG_VALUE', 'False').strip().lower()
allowed_hosts_str = os.getenv('LIST_OF_ALLOWED_HOSTS', default="")
secret_key_value = os.getenv('SECRET_KEY_VALUE')

# Core settings
if not secret_key_value:
    raise ImproperlyConfigured("SECRET_KEY_VALUE environment variable is not set")
SECRET_KEY = secret_key_value
DEBUG = debug_value == 'true'
LIST_OF_ALLOWED_HOSTS = allowed_hosts_str.split(',') if allowed_hosts_str else []
ALLOWED_HOSTS = ["*"] if DEBUG else LIST_OF_ALLOWED_HOSTS

# Admin configuration
ADMIN_NAME = os.getenv('ADMIN_NAME', default="")
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', default="")

# Site configuration
SITE_ID = 1
SITE_NAME = os.getenv('SITE_NAME', 'Quirky Little Tour Company')
SITE_DESCRIPTION = os.getenv('SITE_DESCRIPTION', 'Bible Tour Louvre Application')
DEVELOPMENT_MODE = os.getenv('DEVELOPMENT_MODE', 'false').strip().lower() == 'true'

# --- Apps ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local
    "apps.accounts",
    "apps.pages",
    "apps.legal",
    "apps.booking",
    "apps.payments",
    "apps.shop",
]

AUTH_USER_MODEL = "accounts.User"

# --- Middleware ---
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "apps.payments.context_processors.cart_context",
                "apps.shop.context_processors.shop_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- Auth ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# User activity tracking
USER_ONLINE_TIMEOUT = 300  # 5 minutes
USER_LAST_SEEN_TIMEOUT = 60 * 60 * 24 * 7  # 1 week

# Session configuration
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1800  # 30 minutes in seconds
SESSION_SAVE_EVERY_REQUEST = True

# Message storage
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# Admin configuration
ADMINS = [
    (ADMIN_NAME, ADMIN_EMAIL),
]
MANAGERS = ADMINS

# Security settings for production
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    csrf_trusted_str = os.getenv("CSRF_TRUSTED_ORIGINS", "")
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_trusted_str.split(",") if o.strip()]

# Email configuration
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', default="")
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', default="")

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = EMAIL_HOST_PASSWORD

# Conditional TLS/SSL based on port
EMAIL_USE_TLS = EMAIL_PORT != 465
EMAIL_USE_SSL = EMAIL_PORT == 465

EMAIL_SUBJECT_PREFIX = ""
EMAIL_USE_LOCALTIME = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER


# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose' if DEBUG else 'simple',
            'level': 'DEBUG' if DEBUG else 'ERROR',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'homepage.views': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'bookings.views': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django.core.mail': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'smtplib': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'administration.views': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'bookings.tasks': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django_q': {
            'handlers': ['console'],
            'level': 'ERROR' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
logs_dir = BASE_DIR / 'logs'
if not logs_dir.exists():
    logs_dir.mkdir(parents=True, exist_ok=True)

# URL trailing slash behavior
APPEND_SLASH = True

# Canonical site URL used in outgoing emails (no trailing slash)
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000' if DEBUG else os.getenv('SITE_URL', 'https://reachswim.co.uk')).rstrip('/')

# --- i18n ---
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

# --- Static ---
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Media ---
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Default PK ---
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ---
LOGIN_URL = "/account/login/"
LOGIN_REDIRECT_URL = "/account/profile/"
LOGOUT_REDIRECT_URL = "/"

# --- Stripe ---
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
