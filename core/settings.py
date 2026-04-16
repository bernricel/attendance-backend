"""
Django settings for core project.

This settings module supports both:
- local development via `.env` + SQLite defaults
- production deployment on Render via environment variables + PostgreSQL
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_env(name: str, default=None, *, required: bool = False):
    """
    Fetch an environment variable with clear error messaging for required keys.
    """
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def _get_bool_env(name: str, default: bool = False) -> bool:
    """
    Parse booleans from environment variables consistently.
    Accepted truthy values: 1, true, yes, on.
    """
    raw = _get_env(name, str(default))
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _get_list_env(name: str, default: str = "") -> list[str]:
    """
    Parse comma-separated environment variables into a clean list of strings.
    """
    raw = _get_env(name, default) or ""
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _normalize_multiline_secret(value: str) -> str:
    """
    Convert escaped newline sequences into real newlines for PEM/env secrets.
    """
    return value.replace("\\n", "\n")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: never hardcode this in source; set it via environment.
SECRET_KEY = _get_env("SECRET_KEY", default="django-dev-secret-key-change-me", required=False)

# DEBUG defaults to True locally, but should be False in Render production.
DEBUG = _get_bool_env("DEBUG", default=True)

if not DEBUG and SECRET_KEY == "django-dev-secret-key-change-me":
    raise ImproperlyConfigured("SECRET_KEY is required when DEBUG=False.")

# Include localhost defaults for local development convenience.
ALLOWED_HOSTS = _get_list_env("ALLOWED_HOSTS", "127.0.0.1,localhost")
render_hostname = _get_env("RENDER_EXTERNAL_HOSTNAME", "")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'users',
    'attendance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves collected static files in production without extra services.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

database_url = _get_env("DATABASE_URL", "")
if database_url:
    # Render PostgreSQL is configured through DATABASE_URL.
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    # Local fallback keeps development simple when DATABASE_URL is not set.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    if not DEBUG:
        raise ImproperlyConfigured("DATABASE_URL is required when DEBUG=False.")


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Project operates in the Philippines, so date validations (e.g. attendance-by-date)
# must use Manila local date boundaries rather than UTC day boundaries.
TIME_ZONE = 'Asia/Manila'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise storage adds cache-friendly hashed filenames for production.
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'users.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

# Frontend origins for development; adjust for production deployment.
CORS_ALLOWED_ORIGINS = _get_list_env(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)

# CSRF trusted origins should include deployed frontend origins in production.
CSRF_TRUSTED_ORIGINS = _get_list_env("CSRF_TRUSTED_ORIGINS", "")

GOOGLE_OAUTH_CLIENT_ID = _get_env("GOOGLE_OAUTH_CLIENT_ID", "")
ALLOWED_GOOGLE_DOMAIN = _get_env("ALLOWED_GOOGLE_DOMAIN", "@ua.edu.ph")
DEFAULT_ATTENDANCE_DEPARTMENT = _get_env("DEFAULT_ATTENDANCE_DEPARTMENT", "CIT")

# DSA keys are loaded from env values (supports escaped newlines like \n).
# Key-pair generation is done outside app runtime
# (for example via OpenSSL), then injected here as environment secrets.
_dsa_private_key_env = _get_env("DSA_PRIVATE_KEY", "")
_dsa_public_key_env = _get_env("DSA_PUBLIC_KEY", "")

if _dsa_private_key_env and _dsa_public_key_env:
    DSA_PRIVATE_KEY = _normalize_multiline_secret(_dsa_private_key_env)
    DSA_PUBLIC_KEY = _normalize_multiline_secret(_dsa_public_key_env)
elif DEBUG:
    # Local-only fallback: read existing PEM files if env keys are not set.
    private_key_path = BASE_DIR / "secure_keys" / "attendance_dsa_private.pem"
    public_key_path = BASE_DIR / "secure_keys" / "attendance_dsa_public.pem"
    DSA_PRIVATE_KEY = private_key_path.read_text(encoding="utf-8") if private_key_path.exists() else ""
    DSA_PUBLIC_KEY = public_key_path.read_text(encoding="utf-8") if public_key_path.exists() else ""
else:
    raise ImproperlyConfigured(
        "DSA_PRIVATE_KEY and DSA_PUBLIC_KEY are required when DEBUG=False."
    )

if not DEBUG:
    # Render sits behind a proxy; these settings enforce secure HTTPS behavior.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = _get_bool_env("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    USE_X_FORWARDED_HOST = True
