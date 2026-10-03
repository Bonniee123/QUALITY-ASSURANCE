# AI-Driven Online Archiving System for the Quality Assurance Office

An AI-powered document archiving system built with Django, featuring TF-IDF keyword extraction, K-Means clustering, Elbow Method optimization, area-scoped uploads, and a rule-based chatbot.

## Features

- **Document Upload & Repository** - Upload PDF, DOCX, XLSX, JPG, PNG with metadata
- **AI Processing** - TF-IDF keywords, Elbow Method, K-Means clustering, duplicate detection
- **QA Checklist** - CRUD for QA areas, criteria, indicators, and requirements
- **Smart Search** - Search across metadata, extracted text, and keywords
- **Dashboard** - Summary cards, Chart.js charts, recent activity
- **Reports** - Inventory, cluster, and recent-upload reports with CSV export
- **AI Chatbot** - Rule-based guidance chatbot (no paid API)
- **User Management** - Role-based access (Admin, QA Head, Faculty)

## Tech Stack

- **Backend**: Django 4.2+, Python 3.10+
- **Frontend**: Bootstrap 5, Bootstrap Icons, Chart.js
- **AI/ML**: scikit-learn (TF-IDF, K-Means), PyPDF2, python-docx, openpyxl
- **Database**: MySQL / MariaDB only, configured through the `MYSQL_*` variables in `.env`

## Quick Start

Run all commands from the **project root** (the folder that contains `manage.py` and the `qa_archiving_system` Django settings package).

### 1. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # Linux/Mac
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run migrations
```bash
python manage.py migrate
```

### 4. Create admin account
```bash
python manage.py create_default_admin
```
Default credentials: **admin / admin123**

### 5. Load sample data
```bash
python manage.py load_sample_data
```

### 6. Run the server
```bash
python manage.py runserver
```

Open http://127.0.0.1:8000 in your browser.

### 7. Run smoke tests (optional)
```bash
python manage.py test documents.tests.test_smoke
```

### Environment variables (production)

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret (required when `DEBUG=False`) |
| `DEBUG` | Set to `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames (defaults to `127.0.0.1,localhost` in dev) |
| `USE_TLS` | Set to `true` behind HTTPS to enable secure cookies and `SECURE_SSL_REDIRECT` |
| `GEMINI_API_KEY` | Optional Google Gemini key (never commit real values) |
| `TESSERACT_CMD` | Optional path to the Tesseract OCR executable (otherwise found on `PATH`, or the default Windows install path is used if present) |
| `AI_AUTO_FULL_PIPELINE_MAX_DOCS` | After bulk upload, full TF-IDF/K-Means runs only if total documents ≤ this (default `75`); larger repos use a light keyword pass until staff runs AI Processing |
| `TRUST_X_FORWARDED_SSL` | `true` behind a TLS-terminating proxy so Django trusts `X-Forwarded-Proto: https` (without enabling full `USE_TLS` redirect stack) |
| `USE_X_FORWARDED_HOST` | `true` when the proxy sends `X-Forwarded-Host` (recommended with nginx / Traefik) |
| `MYSQL_DATABASE` | **Required.** The system runs on MySQL only and refuses to start without it. Install **PyMySQL** after base deps: `pip install -r requirements.txt` then `pip install -r requirements-prod.txt` (or `pip install PyMySQL` only) |
| `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | MySQL connection (defaults: `root`, empty password, `localhost`, `3306`; optional `MYSQL_CONN_MAX_AGE`, default `60`) |
| `DJANGO_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, … — console logging (default `DEBUG` when `DEBUG=True`, else `INFO`) |
| `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` | HSTS tuning when `DEBUG=False` and `USE_TLS=true` |

Setting **`POSTGRES_DB`** (or other old Postgres-only vars) will cause Django to exit with an error: this project is configured for **MySQL only**.

**MySQL driver:** `requirements-prod.txt` pins **PyMySQL** (pure Python, good for Windows + XAMPP). `qa_archiving_system/__init__.py` calls `pymysql.install_as_MySQLdb()` so Django can `import MySQLdb`. On Linux you may optionally use **mysqlclient** instead—then avoid also installing PyMySQL in the same venv unless you know the interaction.

## Documentation & demo

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — system diagram, data flow, limitations, evaluation ideas  
- **[docs/UI_UX_AUDIT.md](docs/UI_UX_AUDIT.md)** — record of each fix and check made to the system, with its tests  
- **[docs/MYSQL_MIGRATION.md](docs/MYSQL_MIGRATION.md)** — how the archive was moved onto MySQL/MariaDB (kept as history)  

## Operations (backup & deploy)

- **Backups**: dump the MySQL database (`mysqldump -u root --databases qa_archive --single-transaction`) and back up the entire `media/` directory before upgrades or migrations.  
- **MySQL production**: create the database once with [`scripts/mysql_setup.sql`](scripts/mysql_setup.sql) (phpMyAdmin **SQL** tab or `mysql < scripts/mysql_setup.sql`). Set `MYSQL_*` in the terminal before Django commands, or use helpers: PowerShell **dot-source** [`scripts/set_mysql_env_xampp.ps1`](scripts/set_mysql_env_xampp.ps1); in **CMD** run `call scripts\set_mysql_env_xampp.bat` then `migrate`, or run [`scripts/migrate_mysql_xampp.bat`](scripts/migrate_mysql_xampp.bat) to migrate in one step. Schedule `mysqldump` for backups; keep `media/` on a volume with snapshots or object storage.  
- **Production install**: `pip install -r requirements.txt -r requirements-prod.txt`, set `MYSQL_DATABASE` (and other `MYSQL_*` as needed), `DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, and proxy-related variables above.  
- **Static files**: `python manage.py collectstatic` before serving with gunicorn + nginx.  
- **Error pages**: custom `templates/404.html`, `403.html`, `403_csrf.html`, `400.html` and `500.html` are used in every mode, `DEBUG=True` included (`qa_archiving_system/error_pages.py`); tracebacks still go to the console. Set `SHOW_DEBUG_ERROR_PAGES=True` to see Django's technical pages while developing.
- **Offline page**: `/offline/` is shown in place of a page that cannot load without a connection (served by the service worker at `/sw.js`; browsers allow it on `localhost` and HTTPS). `/healthz/` answers `204` with no database or session, for the reconnect check and for uptime monitors.
- **Messages**: attachments are limited by `MESSAGE_ATTACHMENT_MAX_MB` (default 15) and `MESSAGE_ATTACHMENTS_PER_MESSAGE` (default 10), and stored privately under `media/message_attachments/` (include it in backups). Voice messages need the page to be on `localhost` or HTTPS, which is what browsers require for the microphone.
- **Deletions**: a bulk delete can be undone for `DELETE_UNDO_SECONDS` (default 10), then the files are removed and the record kept (see Document History). Expired undo windows are closed automatically while anyone uses the system; to close them on a schedule too, run `python manage.py finalize_deletions` every few minutes (Task Scheduler / cron).
- **Security before deployment**: see [`docs/SECURITY_BEFORE_DEPLOYMENT.md`](docs/SECURITY_BEFORE_DEPLOYMENT.md).

## User Roles

| Role | Access |
|------|--------|
| Administrator | Everything a QA Head can do, plus user management, settings, audit log, AI processing, and reports |
| QA Head (`qa_staff`) | The daily workflow across **all** accreditation areas: dashboard, upload, repository, smart search, area submissions, clusters, duplicate review, and document deletion |
| Faculty | Contributor scoped to their **assigned accreditation area(s)**: upload, view, search, and download within those areas; may edit or delete only their own uploads |

## Folder Structure

```
qa_archiving_system/
├── accounts/          # User auth & management
├── documents/         # Document upload & repository
├── ai_processing/     # AI/ML services
├── qa_mapping/        # QA programs (accreditation streams)
├── qa_structure/      # Accreditation areas (the Faculty access boundary)
├── notifications/     # In-app notifications
├── search/            # Smart search
├── dashboard/         # Dashboard analytics
├── chatbot/           # Rule-based chatbot
├── reports/           # Report generation
├── templates/         # Shared templates (incl. 404/500 error pages)
├── docs/              # Architecture & demo notes for capstone / ops
├── static/            # CSS, JS, images
└── media/             # Uploaded documents
```

## AI Processing Pipeline

1. Text extraction (PDF/DOCX/XLSX; OCR for images and scanned PDFs)
2. Text cleaning & preprocessing
3. TF-IDF keyword extraction
4. Choosing k for each area/document-type group: silhouette score, with the Elbow Method as the fallback (the Elbow chart is shown on AI Processing)
5. K-Means clustering
6. Duplicate detection: SHA-256 exact copies, SequenceMatcher and TF-IDF cosine for text, dHash for images
7. Smart recommendations
