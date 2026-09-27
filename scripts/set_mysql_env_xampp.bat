@echo off
REM CMD only — sets MySQL env vars for THIS Command Prompt window (typical XAMPP).
REM From project root run:  call scripts\set_mysql_env_xampp.bat
REM You MUST use "call" so variables remain after the script finishes.
REM Then: python manage.py migrate

set MYSQL_DATABASE=qa_archive
set MYSQL_USER=root
set MYSQL_PASSWORD=
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306

echo MySQL env set: MYSQL_DATABASE=%MYSQL_DATABASE% ^| MYSQL_USER=%MYSQL_USER% ^| %MYSQL_HOST%:%MYSQL_PORT%
echo If migrate says MySQLdb missing: pip install PyMySQL   or   pip install -r requirements-prod.txt
echo (Install requirements.txt first; requirements-prod.txt is only the MySQL driver.)
echo Next: python manage.py migrate
