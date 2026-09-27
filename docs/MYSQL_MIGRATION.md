# Migrating the QA Archiving System from SQLite to MySQL

Done on 2026-09-03 against XAMPP's MariaDB 10.4.32. This is the exact sequence, plus
the two problems that came up on the way, so it can be repeated on another machine.

## Prerequisites

- MySQL/MariaDB running (XAMPP Control Panel → MySQL → Start).
- The database created once: run [`scripts/mysql_setup.sql`](../scripts/mysql_setup.sql)
  in phpMyAdmin's **SQL** tab, or `mysql -u root < scripts/mysql_setup.sql`.
  It creates `qa_archive` with `utf8mb4` / `utf8mb4_unicode_ci`.
- The PyMySQL driver: `pip install -r requirements-prod.txt`.
  `qa_archiving_system/__init__.py` calls `pymysql.install_as_MySQLdb()` so Django's
  `django.db.backends.mysql` works without the C-based `mysqlclient`.

## Connection settings

Django switches to MySQL as soon as `MYSQL_DATABASE` is set. In PowerShell:

```powershell
$env:MYSQL_DATABASE = "qa_archive"
$env:MYSQL_USER     = "root"
$env:MYSQL_PASSWORD = ""
$env:MYSQL_HOST     = "127.0.0.1"
$env:MYSQL_PORT     = "3306"
```

Unset `MYSQL_DATABASE` to go back to SQLite. Confirm which one is live with:

```powershell
python manage.py shell -c "from django.db import connection; print(connection.vendor)"
```

## Step 1 — load the MySQL time zone tables (required)

**Do this before running the app**, or the dashboard returns HTTP 500.

With `USE_TZ = True`, every date truncation Django performs (the dashboard's monthly
charts, for example) is compiled to `CONVERT_TZ(col, 'UTC', 'Asia/Manila')`. MariaDB
returns `NULL` for a named zone it does not know, and Django raises:

```
ValueError: Database returned an invalid datetime value.
            Are time zone definitions for your database installed?
```

The documented fix is `mysql_tzinfo_to_sql /usr/share/zoneinfo`, which does not work
here: Windows has no `/usr/share/zoneinfo`, and XAMPP's `mysql_tzinfo_to_sql.exe`
rejects every zone file it is pointed at ("not regular file or directory").

Use the generator in this repo instead — it builds the same SQL from dateutil's
bundled IANA database, with no download and no Unix tooling:

```powershell
python scripts/generate_mysql_timezones.py > scripts/mysql_timezones.sql
& "C:\xampp\mysql\bin\mysql.exe" -u root -h 127.0.0.1 < scripts\mysql_timezones.sql
```

A pre-generated `scripts/mysql_timezones.sql` (UTC + Asia/Manila) is committed. Pass
zone names as arguments, or `--all`, if you change `TIME_ZONE`.

Verify — this must print `2026-09-03 12:00:00`, not `NULL`:

```sql
SELECT CONVERT_TZ('2026-09-03 04:00:00','UTC','Asia/Manila');
```

## Step 2 — create the schema

```powershell
python manage.py migrate
```

Two data migrations seed rows here: `qa_mapping.0004_seed_qa_programs` (6 programs)
and `qa_structure.0002_seed_areas_and_categories`. The import in step 4 overwrites
them by primary key, so they do not need removing.

## Step 3 — export from SQLite

```powershell
$env:PYTHONIOENCODING = "utf-8"
python manage.py dumpdata `
  --exclude contenttypes --exclude auth.Permission `
  --exclude sessions --exclude admin.logentry `
  --indent 2 > scripts\sqlite_export.json
```

Two things matter here:

- **`PYTHONIOENCODING=utf-8` and a shell redirect, not `--output`.** Django's
  `--output` writes with the Windows ANSI codepage, and the export dies on the first
  non-cp1252 character:
  `'charmap' codec can't encode character '\u2192'` (a `→` in the seeded data).
- **Do not pass `--natural-primary`.** Primary keys must be preserved so the import
  updates the seeded rows in place instead of colliding with them on unique
  constraints. `contenttypes` and `auth.Permission` are excluded because Django
  regenerates both from the model registry after `migrate`.

## Step 4 — import into MySQL

```powershell
python manage.py flush --no-input     # clears the seeded rows for an exact copy
python manage.py loaddata scripts\sqlite_export.json
```

## Step 5 — verify

Compare row counts on both backends before trusting the copy. The 2026-09-03 run
matched exactly across all 14 models (24 documents, 9 users, 833 activity logs),
including the full set of `Document.content_sha256` hashes and titles.

## Problems encountered

**`UserProfile` duplicate on load.** `accounts/signals.py` created a profile on every
`post_save` of a `User`, including during fixture loading, colliding with the
profiles in the fixture:

```
Could not load accounts.UserProfile(pk=4): (1062, "Duplicate entry '4' for key 'user_id'")
```

Django passes `raw=True` to `post_save` during `loaddata` precisely so signals can
skip. Both receivers now check it. Without that fix, **no** fixture containing users
can be loaded — this blocked backup restores too, not just this migration.

**Corrupt Aria transaction log (XAMPP-specific, pre-existing).** MariaDB keeps the
`mysql.*` system tables — including the time zone tables — on the Aria engine. If the
Aria log is damaged, every write to them fails and re-corrupts the index:

```
Error writing file 'C:\xampp\mysql\data\aria_log.00000001' (Errcode: 9 "Bad file descriptor")
ERROR 1034 (HY000): Index for table 'time_zone' is corrupt; try to repair it
```

`REPAIR TABLE` succeeds and then breaks again on the next write. The fix is to reset
the log — with **mysqld stopped**:

1. Back up `aria_log.00000001` and `aria_log_control` from `C:\xampp\mysql\data`.
2. Delete both. MariaDB recreates them on the next start.
3. Start MariaDB and confirm a write to an Aria table succeeds.

All application data is InnoDB and is untouched by this. Note that the same fault
also blocks MySQL user and privilege changes, since `mysql.db`, `global_priv`,
`tables_priv`, and `proc` are Aria as well.

## Switching back

Unset `MYSQL_DATABASE`. `db.sqlite3` is never modified by any of the above — the
export only reads from it — so it stays a complete, working fallback.
