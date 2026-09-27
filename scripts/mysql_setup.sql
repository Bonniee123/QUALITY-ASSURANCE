-- =============================================================================
-- QA Archiving System — MySQL / MariaDB bootstrap (e.g. XAMPP phpMyAdmin → SQL)
-- =============================================================================
-- This file only creates an empty database with utf8mb4. It does NOT create
-- application tables — after running this, point Django at MySQL, then migrate:
--   PowerShell:  . .\scripts\set_mysql_env_xampp.ps1
--   CMD:         call scripts\set_mysql_env_xampp.bat   (then migrate), or: scripts\migrate_mysql_xampp.bat
-- Or set MYSQL_DATABASE=qa_archive (and MYSQL_*) yourself in the same terminal, then:
--   pip install -r requirements.txt
--   pip install -r requirements-prod.txt
--   python manage.py migrate
-- =============================================================================

CREATE DATABASE IF NOT EXISTS qa_archive
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- Use the database (optional in phpMyAdmin if you already selected it)
USE qa_archive;

-- -----------------------------------------------------------------------------
-- Optional: dedicated MySQL user (recommended instead of root for shared PCs)
-- Uncomment, set a strong password, run once. If the user already exists,
-- you may get an error — that is safe to ignore or drop the user first.
-- -----------------------------------------------------------------------------
-- CREATE USER 'qa_archive'@'localhost' IDENTIFIED BY 'CHANGE_THIS_PASSWORD';
-- GRANT ALL PRIVILEGES ON qa_archive.* TO 'qa_archive'@'localhost';
-- FLUSH PRIVILEGES;
