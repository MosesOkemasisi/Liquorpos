import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


_DEV_KEY = "dev-only-insecure-key-change-me"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", _DEV_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and SECRET_KEY == _DEV_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "inventory",
    "sales",
    "payments",
    "reports",
    "shop",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context.store",
                "inventory.context_processors.staff_counters",
                "shop.context_processors.cart_count",
            ],
        },
    },
]

# ---- Database: PostgreSQL when DB_NAME is set, otherwise SQLite for quick local tests ----
if os.getenv("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "staff_home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Uploaded product photos
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ---- Store details used on receipts and the online shop ----
STORE = {
    "name": os.getenv("STORE_NAME", "Your Liquor Store"),
    "address": os.getenv("STORE_ADDRESS", ""),
    "phone": os.getenv("STORE_PHONE", ""),
    "kra_pin": os.getenv("STORE_KRA_PIN", ""),
    "licence": os.getenv("STORE_LIQUOR_LICENCE", ""),
    "min_age": 18,
}

# ---- M-Pesa / Daraja ----
_shortcode = os.getenv("MPESA_SHORTCODE", "174379")
MPESA = {
    "ENV": os.getenv("MPESA_ENV", "sandbox").strip().lower(),
    "CONSUMER_KEY": os.getenv("MPESA_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": os.getenv("MPESA_CONSUMER_SECRET", ""),
    "SHORTCODE": _shortcode,
    "PASSKEY": os.getenv("MPESA_PASSKEY", ""),
    "TRANSACTION_TYPE": os.getenv("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
    "PARTY_B": os.getenv("MPESA_PARTY_B") or _shortcode,
    "CALLBACK_BASE_URL": os.getenv("MPESA_CALLBACK_BASE_URL", "").rstrip("/"),
    "CALLBACK_SECRET": os.getenv("MPESA_CALLBACK_SECRET", "change-me"),
    "SIMULATE": env_bool("MPESA_SIMULATE", False),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "payments": {"handlers": ["console"], "level": "INFO"},
        "sales": {"handlers": ["console"], "level": "INFO"},
    },
}
