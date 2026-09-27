import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
django.setup()
from django.test import RequestFactory
from dashboard.views import dashboard_home
from django.contrib.auth.models import User

request = RequestFactory().get('/')
request.user = User.objects.first()
try:
    response = dashboard_home(request)
    print('STATUS:', response.status_code)
    print('SUCCESS')
except Exception as e:
    import traceback
    traceback.print_exc()
