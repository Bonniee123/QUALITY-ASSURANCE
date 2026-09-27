@echo off
REM Run from project root (folder that contains manage.py), double-click or: scripts\migrate_mysql_xampp.bat
REM Uses typical XAMPP defaults; edit SET lines if your MySQL user/password differ.

cd /d "%~dp0.."

set MYSQL_DATABASE=qa_archive
set MYSQL_USER=root
set MYSQL_PASSWORD=
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306

echo Using MySQL: %MYSQL_HOST%:%MYSQL_PORT% database=%MYSQL_DATABASE%
python manage.py migrate
if errorlevel 1 pause
pause
