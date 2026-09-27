#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def _project_venv_python():
    """Return the local venv interpreter path when present."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == 'win32':
        candidate = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
    else:
        candidate = os.path.join(base_dir, 'venv', 'bin', 'python')
    return candidate if os.path.isfile(candidate) else None


def _reexec_with_project_venv():
    """
    If dependencies live in ./venv, re-run this script with that interpreter so
    `python manage.py runserver` works without manually activating the venv.
    """
    venv_python = _project_venv_python()
    if not venv_python:
        return
    current = os.path.normcase(os.path.abspath(sys.executable))
    target = os.path.normcase(os.path.abspath(venv_python))
    if current != target:
        import subprocess

        completed = subprocess.run([venv_python, *sys.argv], check=False)
        raise SystemExit(completed.returncode)


def _ensure_local_runserver_env():
    """
    Reset leftover production env vars so `runserver` works on localhost.

    If you tested check_production with DEBUG=False / USE_TLS=true in PowerShell,
    those variables stay in the shell and break login, static files, and media.
    """
    if len(sys.argv) < 2 or sys.argv[1] != 'runserver':
        return
    if os.environ.get('QA_ALLOW_PROD_SERVER', '').lower() in ('1', 'true', 'yes'):
        return

    changed = []
    if os.environ.get('DEBUG', 'True').strip().lower() in ('0', 'false', 'no'):
        os.environ['DEBUG'] = 'True'
        changed.append('DEBUG=True')
    if os.environ.get('USE_TLS', '').strip().lower() in ('1', 'true', 'yes'):
        os.environ['USE_TLS'] = 'False'
        changed.append('USE_TLS=False')

    hosts = {
        h.strip().lower()
        for h in os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
        if h.strip()
    }
    if hosts.isdisjoint({'127.0.0.1', 'localhost'}):
        os.environ['ALLOWED_HOSTS'] = '127.0.0.1,localhost'
        changed.append('ALLOWED_HOSTS=127.0.0.1,localhost')

    if changed:
        print('[QA Archive] Reset local dev settings:', ', '.join(changed))
        print('[QA Archive] Tip: run scripts\\reset_dev_env.ps1 or open a new terminal.')


def main():
    """Run administrative tasks."""
    _reexec_with_project_venv()
    _ensure_local_runserver_env()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
