"""
WSGI config for QA Archiving System.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
application = get_wsgi_application()
