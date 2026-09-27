"""
ASGI config for QA Archiving System.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
application = get_asgi_application()
