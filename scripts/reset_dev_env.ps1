# Clear production environment variables that break local runserver.
# Run in PowerShell before starting the app:
#   powershell -ExecutionPolicy Bypass -File scripts\reset_dev_env.ps1

Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
Remove-Item Env:USE_TLS -ErrorAction SilentlyContinue
Remove-Item Env:TRUST_X_FORWARDED_SSL -ErrorAction SilentlyContinue
Remove-Item Env:CSRF_TRUSTED_ORIGINS -ErrorAction SilentlyContinue
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ALLOWED_HOSTS -ErrorAction SilentlyContinue
Remove-Item Env:QA_ALLOW_PROD_SERVER -ErrorAction SilentlyContinue

Write-Host "Development environment variables cleared." -ForegroundColor Green
Write-Host "Start the app with: python manage.py runserver" -ForegroundColor Cyan
