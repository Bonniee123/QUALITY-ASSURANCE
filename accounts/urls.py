"""
URL patterns for accounts app.
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    # Turns an account's access on or off from the user table.
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('settings/', views.settings_view, name='settings'),
    path('audit-log/', views.audit_log, name='audit_log'),
    # Departments fill the dropdown on the account forms and are managed from
    # there, so these answer JSON rather than serving pages of their own.
    # Administrator only, same as the rest of user management.
    path('departments/list/', views.department_quick_list, name='department_quick_list'),
    path('departments/add/', views.department_quick_add, name='department_quick_add'),
    path('departments/<int:pk>/remove/', views.department_quick_delete, name='department_quick_delete'),
]
