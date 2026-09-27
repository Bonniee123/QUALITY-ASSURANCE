"""
Django settings for QA Archiving System.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """
    Read a .env file in the project root into the environment.

    Every setting below is read with os.getenv, which looks at real environment
    variables and knows nothing about a file. Without this, a .env sitting next
    to manage.py is simply ignored, and a key put there looks configured while
    having no effect at all.

    A value already set in the real environment always wins, so running the
    server with a variable on the command line still overrides the file.
    Anything malformed is skipped rather than raising, because a stray line in
    this file must never stop the system from starting.
    """
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.lower().startswith('export '):
            line = line[7:]
        name, _, value = line.partition('=')
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ[name] = value


_load_env_file(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
# POLICY ENFORCEMENT: No Secrets In Code
SECRET_KEY = os.getenv(
    'SECRET_KEY', 
    'django-insecure-qa-archive-dev-key-change-in-production-2024'
)

# SECURITY WARNING: don't run with debug turned on in production!
# POLICY ENFORCEMENT: Fail Closed on missing environment variables
DEBUG = os.getenv('DEBUG', 'True') == 'True'

if not DEBUG and SECRET_KEY == 'django-insecure-qa-archive-dev-key-change-in-production-2024':
    raise ValueError("CRITICAL: A secure SECRET_KEY environment variable must be set in production (DEBUG=False).")

# Even with DEBUG on, visitors get the app's own error pages (templates/404.html, 500.html, ...) instead of
# Django's technical ones; tracebacks still go to the console. Set True to see Django's pages while developing.
SHOW_DEBUG_ERROR_PAGES = os.getenv('SHOW_DEBUG_ERROR_PAGES', 'False').strip().lower() in ('1', 'true', 'yes')

# Host header validation — default to local dev; set ALLOWED_HOSTS in production (comma-separated)
_raw_hosts = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').strip()
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(',') if h.strip()]

# Production: reject localhost-only hosts (prevents accidental open deployment misconfiguration).
if not DEBUG:
    _prod_hosts = {h.strip().lower() for h in ALLOWED_HOSTS}
    if _prod_hosts <= {'127.0.0.1', 'localhost'}:
        raise ImproperlyConfigured(
            'ALLOWED_HOSTS must include your production domain or IP when DEBUG=False.'
        )

# HTTPS / cookie hardening when deploying behind TLS (set USE_TLS=true)
USE_TLS = os.getenv('USE_TLS', 'False').strip().lower() in ('1', 'true', 'yes')
# Trust X-Forwarded-Proto from a reverse proxy without forcing SECURE_SSL_REDIRECT (avoids redirect loops if misconfigured)
TRUST_X_FORWARDED_SSL = os.getenv('TRUST_X_FORWARDED_SSL', 'False').strip().lower() in ('1', 'true', 'yes')
# Use X-Forwarded-Host when behind nginx / Traefik (set True in production behind a proxy)
USE_X_FORWARDED_HOST = os.getenv('USE_X_FORWARDED_HOST', 'False').strip().lower() in ('1', 'true', 'yes')
# Read the client IP from X-Forwarded-For (login lockout, rate limits, audit log). Only behind a proxy you
# control: without one, any client can write that header and dodge the per-IP lockout.
TRUST_X_FORWARDED_FOR = os.getenv('TRUST_X_FORWARDED_FOR', 'False').strip().lower() in ('1', 'true', 'yes')

if USE_TLS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
if USE_TLS or TRUST_X_FORWARDED_SSL:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Allow the in-app document viewer to embed PDF/DOCX previews (iframe/embed on same origin).
X_FRAME_OPTIONS = 'SAMEORIGIN'

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    if USE_TLS:
        SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
        SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv(
            'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True'
        ).strip().lower() in ('1', 'true', 'yes')
        SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'False').strip().lower() in ('1', 'true', 'yes')

# CSRF origin allowlist for HTTPS deployments (comma-separated full origins).
_raw_csrf = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
if _raw_csrf:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _raw_csrf.split(',') if o.strip()]
elif not DEBUG and USE_TLS:
    CSRF_TRUSTED_ORIGINS = [
        f'https://{host}' for host in ALLOWED_HOSTS
        if host and host not in ('127.0.0.1', 'localhost')
    ]
else:
    CSRF_TRUSTED_ORIGINS = []

# DOCX in-browser preview: auto = docx-preview unless LibreOffice/Word is installed for PDF conversion
DOCX_PREVIEW_MODE = os.getenv('DOCX_PREVIEW_MODE', 'auto').strip().lower()

# Optional absolute path to LibreOffice soffice.exe (Windows/Linux) for faithful DOCX→PDF previews
LIBREOFFICE_PATH = os.getenv('LIBREOFFICE_PATH', '').strip()

# After bulk upload, run full TF-IDF/K-Means on entire corpus only when document count is at or below this (reduces timeouts on large repos)
AI_AUTO_FULL_PIPELINE_MAX_DOCS = int(os.getenv('AI_AUTO_FULL_PIPELINE_MAX_DOCS', '75'))

# Below this many characters a document is not characterised well enough for
# cosine similarity over its terms to mean anything. Two unrelated flowcharts
# whose OCR yields a dozen shared words ("The system", "uploads document")
# scored 1.000 against each other and were both flagged for review. Images are
# excluded from the text check outright and judged by perceptual hash instead;
# this covers everything else that happens to be short.
DUPLICATE_TEXT_MIN_CHARS = int(os.getenv('DUPLICATE_TEXT_MIN_CHARS', '400'))

# Smart clustering: group within accreditation area + document type, hybrid features, merge pass.
AI_CLUSTER_WITHIN_AREA = os.getenv('AI_CLUSTER_WITHIN_AREA', 'True').strip().lower() in ('1', 'true', 'yes')
AI_CLUSTER_WITHIN_DOC_TYPE = os.getenv('AI_CLUSTER_WITHIN_DOC_TYPE', 'True').strip().lower() in ('1', 'true', 'yes')
AI_CLUSTER_MAX_K = int(os.getenv('AI_CLUSTER_MAX_K', '8'))
AI_CLUSTER_MIN_SILHOUETTE = float(os.getenv('AI_CLUSTER_MIN_SILHOUETTE', '0.08'))
AI_CLUSTER_PAIR_SIMILARITY = float(os.getenv('AI_CLUSTER_PAIR_SIMILARITY', '0.35'))
AI_CLUSTER_MERGE_SIMILARITY = float(os.getenv('AI_CLUSTER_MERGE_SIMILARITY', '0.7'))
AI_CLUSTER_HYBRID_METADATA = os.getenv('AI_CLUSTER_HYBRID_METADATA', 'True').strip().lower() in ('1', 'true', 'yes')
AI_CLUSTER_METADATA_WEIGHT = float(os.getenv('AI_CLUSTER_METADATA_WEIGHT', '1.5'))
AI_CLUSTER_DAVIES_MAX_SAMPLES = int(os.getenv('AI_CLUSTER_DAVIES_MAX_SAMPLES', '500'))
# Optional semantic embeddings (pip install -r requirements-ai.txt).
# Default: auto — enabled when sentence-transformers is installed, unless explicitly disabled.
_ai_emb_env = os.getenv('AI_CLUSTER_USE_EMBEDDINGS', 'auto').strip().lower()
if _ai_emb_env in ('1', 'true', 'yes'):
    AI_CLUSTER_USE_EMBEDDINGS = True
elif _ai_emb_env in ('0', 'false', 'no'):
    AI_CLUSTER_USE_EMBEDDINGS = False
else:
    # Detect the package WITHOUT importing it: a bare `import sentence_transformers`
    # here would pull torch + transformers into every Django process (runserver,
    # migrate, test, even `manage.py check`) before any app code runs.
    # find_spec only inspects the module finder, so the cost stays near zero and
    # torch is imported lazily by ai_processing.embedding_service when actually used.
    import importlib.util

    AI_CLUSTER_USE_EMBEDDINGS = importlib.util.find_spec('sentence_transformers') is not None
AI_CLUSTER_EMBEDDING_MODEL = os.getenv('AI_CLUSTER_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
AI_CLUSTER_EMBEDDING_MAX_CHARS = int(os.getenv('AI_CLUSTER_EMBEDDING_MAX_CHARS', '12000'))
# Loading the embedding model takes about 730 MB on top of the running server.
# With less memory than this free (RAM plus the page file's room to grow), a
# clustering run uses TF-IDF instead of risking a load that could crash the
# server. 0 turns the check off.
AI_CLUSTER_EMBEDDING_MIN_FREE_MB = int(os.getenv('AI_CLUSTER_EMBEDDING_MIN_FREE_MB', '1536'))

# Auto-Map text clipping — keep each HTTP request short (browser waits for the full response).
AUTOMAP_MAX_DOCUMENTS = int(os.getenv('AUTOMAP_MAX_DOCUMENTS', '25'))
AUTOMAP_MAX_TEXT_CHARS = int(os.getenv('AUTOMAP_MAX_TEXT_CHARS', '24000'))

# Hybrid smart search (lexical retrieval + semantic-style reranking of top candidates).
ENABLE_HYBRID_SMART_SEARCH = os.getenv('ENABLE_HYBRID_SMART_SEARCH', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)
HYBRID_SEARCH_CANDIDATE_POOL = int(os.getenv('HYBRID_SEARCH_CANDIDATE_POOL', '200'))
HYBRID_SEARCH_MAX_RANKED = int(os.getenv('HYBRID_SEARCH_MAX_RANKED', '120'))

# Hide advanced QA tools from navigation/content by default. This used to gate
# the QA Checklist as well; that page was removed, so it now covers the
# AI & Analysis entries only.
HIDE_ADVANCED_QA_TOOLS = os.getenv('HIDE_ADVANCED_QA_TOOLS', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)

# Simple UI mode for non-technical office users (QA Head role): keep only core daily workflow pages.
SIMPLE_UI_FOR_QA_HEAD = os.getenv('SIMPLE_UI_FOR_QA_HEAD', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    # Before django.contrib.staticfiles: when two apps provide the same command,
    # Django uses the one listed FIRST. This app was listed last "so its runserver
    # overrides staticfiles'", which does the opposite -- staticfiles' runserver
    # ran, and the project's (resume and recover background jobs at start-up,
    # first-run setup) never did. The project command extends staticfiles' one,
    # so static files are still served in development.
    'qa_archiving_system.apps.QAArchivingSystemConfig',
    'django.contrib.staticfiles',
    # Project apps
    'accounts',
    'documents',
    'ai_processing',
    'qa_mapping',
    'qa_structure',
    'search',
    'dashboard',
    'chatbot',
    'reports',
    'notifications',
    'messaging',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'qa_archiving_system.middleware.SecurityHeadersMiddleware',
    'qa_archiving_system.middleware.BlockPublicMediaMiddleware',
    'qa_archiving_system.error_pages.FriendlyErrorPagesMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'accounts.middleware.SessionIdleTimeoutMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'qa_archiving_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.sidebar_badges',
                'accounts.context_processors.rbac_context',
                'notifications.context_processors.notifications_context',
                'messaging.context_processors.messaging_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'qa_archiving_system.wsgi.application'

# Database — MySQL only.
#
# This system used to fall back to SQLite whenever MYSQL_DATABASE was unset,
# which was convenient but dangerous: a missing line in .env did not raise an
# error, it quietly pointed the whole system at a different, empty database and
# the archive appeared to have lost every document. The archive now lives in
# MySQL alone, so a missing configuration is a mistake worth stopping for rather
# than working around.
#
# PostgreSQL is not supported in this project configuration.
if os.getenv('POSTGRES_DB', '').strip():
    raise ImproperlyConfigured(
        'POSTGRES_DB is set but this deployment uses MySQL. '
        'Unset POSTGRES_* and set MYSQL_DATABASE (+ MYSQL_USER, etc.).'
    )

_mysql_db = os.getenv('MYSQL_DATABASE', '').strip()
if not _mysql_db:
    raise ImproperlyConfigured(
        'MYSQL_DATABASE is not set. This system runs on MySQL only and will not '
        'start without it. Put the database settings in the .env file beside '
        'manage.py, for example:\n'
        '    MYSQL_DATABASE=qa_archive\n'
        '    MYSQL_USER=root\n'
        '    MYSQL_PASSWORD=\n'
        '    MYSQL_HOST=127.0.0.1\n'
        '    MYSQL_PORT=3306\n'
        'Check that MySQL is running before starting the server.'
    )

if _mysql_db:
    try:
        import MySQLdb  # noqa: F401
    except ImportError as exc:
        raise ImproperlyConfigured(
            'MYSQL_DATABASE is set but the MySQL driver is missing (could not import MySQLdb). '
            'Install PyMySQL (used as MySQLdb via qa_archiving_system/__init__.py): '
            'pip install PyMySQL   or   pip install -r requirements-prod.txt '
            '(after pip install -r requirements.txt — do not use requirements-prod alone to pull the full stack).'
        ) from exc
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': _mysql_db,
            'USER': os.getenv('MYSQL_USER', 'root').strip(),
            'PASSWORD': os.getenv('MYSQL_PASSWORD', ''),
            'HOST': os.getenv('MYSQL_HOST', 'localhost').strip(),
            'PORT': os.getenv('MYSQL_PORT', '3306').strip(),
            'CONN_MAX_AGE': int(os.getenv('MYSQL_CONN_MAX_AGE', '60')),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (uploaded documents)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Where area ZIP downloads are assembled before they are sent (deleted as soon as
# the download closes). Beside the project rather than the system temp folder.
ZIP_TEMP_DIR = os.getenv('ZIP_TEMP_DIR', str(BASE_DIR / 'tmp'))

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login/Logout URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Authentication hardening
# Session expires after 8 hours; idle timeout logs out after 1 hour with no activity.
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', str(8 * 60 * 60)))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_IDLE_TIMEOUT = int(os.getenv('SESSION_IDLE_TIMEOUT', str(60 * 60)))

# Brute-force protection on /accounts/login/ (per IP and per username).
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv('LOGIN_RATE_LIMIT_ATTEMPTS', '5'))
LOGIN_RATE_LIMIT_WINDOW = int(os.getenv('LOGIN_RATE_LIMIT_WINDOW', '900'))
LOGIN_RATE_LIMIT_LOCKOUT = int(os.getenv('LOGIN_RATE_LIMIT_LOCKOUT', '900'))

# Per-account, per-device limits on the heavy actions (qa_archiving_system.rate_limit): requests allowed per window
# (seconds). Normal use stays far below them. A limit of 0 turns that check off.
CHATBOT_RATE_LIMIT = int(os.getenv('CHATBOT_RATE_LIMIT', '20'))
CHATBOT_RATE_LIMIT_WINDOW = int(os.getenv('CHATBOT_RATE_LIMIT_WINDOW', '60'))
UPLOAD_RATE_LIMIT = int(os.getenv('UPLOAD_RATE_LIMIT', '15'))
UPLOAD_RATE_LIMIT_WINDOW = int(os.getenv('UPLOAD_RATE_LIMIT_WINDOW', '600'))
ZIP_RATE_LIMIT = int(os.getenv('ZIP_RATE_LIMIT', '10'))
ZIP_RATE_LIMIT_WINDOW = int(os.getenv('ZIP_RATE_LIMIT_WINDOW', '600'))

# Which language model the chatbot falls back to when its own tiers -- live data,
# accreditation FAQ, navigation and the scope guard -- do not answer a question.
#
#   'ollama'  a model running on this machine. No key and no cost, but the
#             machine has to be running it. This is the default, so nothing
#             changes for anyone who does not set the variable.
#   'gemini'  Google's hosted model. Needs GEMINI_API_KEY. Useful once the
#             system is deployed somewhere that cannot run a model of its own.
#   'none'    no model at all; the rule tiers answer on their own.
#
# GEMINI_FALLBACK_TO_OLLAMA keeps the local model as a second chance when the
# hosted one is unreachable or out of quota, so the chatbot never goes silent.
CHATBOT_LLM_PROVIDER = os.getenv('CHATBOT_LLM_PROVIDER', 'ollama').strip().lower()
CHATBOT_LLM_TIMEOUT = int(os.getenv('CHATBOT_LLM_TIMEOUT', '25'))

# The key is read from the environment and never written into this file, so it
# cannot reach the repository or a submitted copy of the project.
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite').strip()
GEMINI_API_BASE = os.getenv(
    'GEMINI_API_BASE', 'https://generativelanguage.googleapis.com/v1beta/models').strip()
GEMINI_FALLBACK_TO_OLLAMA = os.getenv(
    'GEMINI_FALLBACK_TO_OLLAMA', 'True').strip().lower() in ('1', 'true', 'yes')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'qa-archive-auth',
    }
}

# File upload max size (25MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# Bulk upload: only BULK_UPLOAD_MAX_FILES are saved per request; extras are ignored (see documents.views.bulk_upload).
# DATA_UPLOAD_MAX_NUMBER_FILES is the multipart parser cap (must be high enough that a large folder pick still
# parses so the view can truncate); it is not the same as the 100-file business limit.
BULK_UPLOAD_MAX_FILES = int(os.getenv('BULK_UPLOAD_MAX_FILES', '100'))
DATA_UPLOAD_MAX_NUMBER_FILES = int(
    os.getenv('DATA_UPLOAD_MAX_NUMBER_FILES', str(max(BULK_UPLOAD_MAX_FILES, 500)))
)
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv('DATA_UPLOAD_MAX_NUMBER_FIELDS', '2000'))

# Allowed file extensions for document upload
ALLOWED_UPLOAD_EXTENSIONS = ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png']

# Google Gemini API key — never commit real keys; set GEMINI_API_KEY in the environment
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# OCR — optional path to the Tesseract binary; leave empty to use system PATH
TESSERACT_CMD = os.getenv('TESSERACT_CMD', '')
OCR_LANGUAGE = os.getenv('OCR_LANGUAGE', 'eng')
ENABLE_PDF_OCR_FALLBACK = os.getenv('ENABLE_PDF_OCR_FALLBACK', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)
PDF_OCR_MIN_TEXT_CHARS = int(os.getenv('PDF_OCR_MIN_TEXT_CHARS', '120'))
PDF_OCR_MAX_FILE_MB = int(os.getenv('PDF_OCR_MAX_FILE_MB', '20'))
PDF_OCR_MAX_PAGES = int(os.getenv('PDF_OCR_MAX_PAGES', '6'))
DUPLICATE_SIMILARITY_THRESHOLD = float(os.getenv('DUPLICATE_SIMILARITY_THRESHOLD', '0.85'))
# Pre-upload near-duplicate guard (text-level) to block almost-identical file uploads.
DUPLICATE_PREUPLOAD_TEXT_THRESHOLD = float(os.getenv('DUPLICATE_PREUPLOAD_TEXT_THRESHOLD', '0.95'))
DUPLICATE_PREUPLOAD_MIN_TEXT_CHARS = int(os.getenv('DUPLICATE_PREUPLOAD_MIN_TEXT_CHARS', '150'))
# Visual (perceptual-hash) duplicate detection for images. Lower distance = stricter.
# A 64-bit dHash; distance 10 ~= 84% visual similarity. Range 0 (identical) to 64.
# Hamming distance under which two perceptual hashes are called the same image.
#
# This was 10, which is loose enough to be wrong on line art: a flowchart is thin
# black strokes on white, so unrelated diagrams hash alike. At 10 the system
# paired figure5-system-architecture with figure6-deployment-diagram, and
# FLOWCHART.png with bookings.png, and asked a human to review both.
#
# Measured over the 55 images in the archive, every pair at distance 4 or below
# is the same figure re-uploaded; the false pairs start at 6. Five is the
# conventional "same image" threshold for pHash and sits inside that gap.
IMAGE_PHASH_MAX_DISTANCE = int(os.getenv('IMAGE_PHASH_MAX_DISTANCE', '5'))

# Beyond the conclusive distance above, two images may still be the same figure
# re-exported at a different size -- close, but not close enough for pixels alone
# to separate them from a genuinely different diagram. Inside this wider band a
# second signal has to agree: the file names must match once version suffixes
# are stripped. Measured over the archive, same-figure pairs score 1.00 on that
# and unrelated pairs score 0.06-0.47, so the two do not overlap.
#
# A match in this band is flagged for review, never used to block an upload:
# a revised figure legitimately looks like its predecessor, and refusing it
# would stop real work.
IMAGE_PHASH_REVIEW_DISTANCE = int(os.getenv('IMAGE_PHASH_REVIEW_DISTANCE', '10'))
IMAGE_NAME_MATCH_RATIO = float(os.getenv('IMAGE_NAME_MATCH_RATIO', '0.85'))
AI_USE_BACKGROUND_JOBS = os.getenv('AI_USE_BACKGROUND_JOBS', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)
# When True, newly enqueued background jobs are executed immediately in-process.
# This keeps AI features automatic even without running a separate worker command.
AI_RUN_JOBS_INLINE = os.getenv('AI_RUN_JOBS_INLINE', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)
SEARCH_SHOW_EXPLAINABILITY = os.getenv('SEARCH_SHOW_EXPLAINABILITY', 'True').strip().lower() in (
    '1',
    'true',
    'yes',
)

# Logging (override level with DJANGO_LOG_LEVEL=DEBUG|INFO|WARNING)
LOG_LEVEL = os.getenv('DJANGO_LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[{levelname}] {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'documents': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}
