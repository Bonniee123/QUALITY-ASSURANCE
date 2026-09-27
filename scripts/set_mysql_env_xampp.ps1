# PowerShell ONLY (not CMD). Dot-source so variables stay in THIS window:
#   cd "…\QA-Capstone system"
#   . .\scripts\set_mysql_env_xampp.ps1
# In Command Prompt (cmd.exe) use instead:  call scripts\set_mysql_env_xampp.bat
# Then: python manage.py migrate

$env:MYSQL_DATABASE = "qa_archive"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = ""
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"

Write-Host "MySQL (XAMPP-style) env set for this session:" -ForegroundColor Cyan
Write-Host "  MYSQL_DATABASE=$($env:MYSQL_DATABASE)"
Write-Host "  MYSQL_USER=$($env:MYSQL_USER)"
Write-Host "  MYSQL_HOST=$($env:MYSQL_HOST) MYSQL_PORT=$($env:MYSQL_PORT)"
Write-Host ""
Write-Host "Next: python manage.py migrate" -ForegroundColor Green
Write-Host "Verify: python manage.py shell -c `"from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])`""
