# Security checklist before deploying the QA Archiving System

Written 2026-09-16. Today the system runs on one laptop with
`.\venv\Scripts\python.exe manage.py runserver`, which is fine for development and the defense.
Before anyone else can reach it over a network, work through this list in order.

## Already in place (no action needed)

- Every page and download checks sign-in, role and Faculty area on the server.
- Passwords are hashed by Django and must pass the four password validators.
- Login locks for 15 minutes after 5 failed attempts, per IP and per username.
  `/admin/login/` redirects to the same login page, so Django admin has the lockout too.
- Rate limits apply per account and device: 20 QA Assistant messages per minute,
  15 upload batches per 10 minutes and 10 ZIP downloads per 10 minutes.
- Uploaded files are never served straight from `/media/`. They go only through the
  signed-in document views. Profile photos (`/media/profile_pics/`) are the one exception.
- CSRF protection, template auto-escaping, a Content-Security-Policy, `nosniff`,
  `Permissions-Policy` and `X-Frame-Options: DENY` are all on. The two document
  views the file viewer embeds set `SAMEORIGIN` for themselves, so every other
  page refuses to be framed at all.
- Sessions end after 1 hour idle and 8 hours in total.

## 1. Accounts

- Change the default `admin` / `admin123` password
  (User Management, or `manage.py changepassword admin`).
- `manage.py runserver` recreates `admin` / `admin123` whenever no `admin` user exists
  (`qa_archiving_system/management/commands/runserver.py`, which calls
  `accounts/management/commands/create_default_admin.py`). A production server
  (Waitress / gunicorn) does not go through `runserver`. Still, never run
  `create_default_admin` on a deployed copy, and remove that call if `runserver` is ever
  exposed on a shared network.

## 2. Settings (`.env`, from `.env.production.example`)

| Setting | Value |
|---|---|
| `DEBUG` | `False`. With `True`, visitors see error pages that show code and settings. |
| `SECRET_KEY` | A long random string. Startup refuses the development key when `DEBUG=False`. |
| `ALLOWED_HOSTS` | The real host name or IP. Startup refuses localhost-only when `DEBUG=False`. |
| `USE_TLS` | `true` once HTTPS works. Turns on the HTTPS redirect, secure cookies and HSTS. |
| `CSRF_TRUSTED_ORIGINS` | `https://your-host` |
| `TRUST_X_FORWARDED_FOR` | `true` **only** behind your own reverse proxy (nginx). Otherwise leave it `false`, or clients can fake their IP and dodge the lockout. |
| `CHATBOT_RATE_LIMIT`, `UPLOAD_RATE_LIMIT`, `ZIP_RATE_LIMIT` (+ `_WINDOW`) | The defaults are fine. `0` turns one limit off. |

Then run both checks and fix everything they report:

```powershell
.\venv\Scripts\python.exe manage.py check --deploy
.\venv\Scripts\python.exe manage.py check_production
```

## 3. Web server and HTTPS

`runserver` is a development server. For a real deployment:

- **Windows:** Waitress as the app server, plus WhiteNoise or IIS to serve `/static/`
  (run `collectstatic` first). Put HTTPS in front with IIS, Caddy or nginx for Windows.
- **Linux:** gunicorn behind `scripts/nginx_qa_archive.conf.example`, which already
  redirects HTTP to HTTPS and blocks `/media/`.
  - That example blocks **all** of `/media/`, including profile photos, and Django does not
    serve media when `DEBUG=False`. To keep the photos, add a
    `location /media/profile_pics/ { alias /var/www/qa-archive/media/profile_pics/; }`
    block above the `/media/` block.
  - It appends the client address to `X-Forwarded-For`, which is what
    `TRUST_X_FORWARDED_FOR=true` expects (the app reads the last entry).
- Keep `client_max_body_size` (or its equivalent) at 26 MB to match the 25 MB upload limit.

## 4. Dependencies (planned "Step 3", after the defense)

- **Django 4.2 LTS reached end of support in April 2026.** Upgrade to 5.2 LTS.
  Django 5.2 needs MariaDB 10.5 or newer, and XAMPP ships 10.4.32, so upgrade the
  database (or use MySQL 8) first.
- ~~**PyPDF2 is no longer maintained.** Switch to its successor `pypdf`.~~ Done:
  no project file imports PyPDF2 any more.
- Run `pip-audit -r requirements.txt` and update anything it flags, then run the full
  test suite.

## 5. The machine and the data

- Turn on disk encryption (BitLocker) on the server or laptop that holds `media/` and the database.
- Back up the database and `media/` on a schedule, and test a restore at least once.
- Keep Windows, Python and MariaDB/MySQL updated.
