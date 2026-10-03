"""
Root URL configuration for QA Archiving System.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.templatetags.static import static as static_url
from accounts.views import home_redirect
from . import views as site_views

urlpatterns = [
    # Django admin's own sign-in page has no failed-attempt lockout, so it goes
    # through the app's login instead; ?next=/admin/ brings a superuser back.
    path('admin/login/', RedirectView.as_view(pattern_name='accounts:login', query_string=True)),
    path('admin/', admin.site.urls),
    path(
        'favicon.ico',
        RedirectView.as_view(url=static_url('images/qa-logo-favicon.png'), permanent=True),
    ),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('documents/', include('documents.urls')),
    path('ai-processing/', include('ai_processing.urls')),
    path('qa-mapping/', include('qa_mapping.urls')),
    path('search/', include('search.urls')),
    path('reports/', include('reports.urls')),
    path('chatbot/', include('chatbot.urls')),
    path('notifications/', include('notifications.urls')),
    path('messages/', include('messaging.urls')),
    # Reachable without signing in, and needing no database: the offline page,
    # the service worker that serves it, and the "is the server back?" check.
    path('offline/', site_views.offline, name='offline'),
    path('healthz/', site_views.healthz, name='healthz'),
    path('sw.js', site_views.service_worker, name='service_worker'),
    path('', home_redirect, name='home'),
]

# Serve media files in development only — production uses authenticated document views.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
