# Test authentication security against a running dev server.
# Usage (from project root):
#   python manage.py runserver
#   powershell -ExecutionPolicy Bypass -File scripts\test_auth_security.ps1

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cookieJar = Join-Path $env:TEMP "qa_auth_test_cookies.txt"

if (Test-Path $cookieJar) { Remove-Item $cookieJar -Force }

Write-Host "=== QA Archive Authentication Security Test ===" -ForegroundColor Cyan
Write-Host "Server: $base`n"

function Get-HttpCodeAndLocation {
    param([string]$Url)
    $out = curl.exe -s -o NUL -w "%{http_code}|%{redirect_url}" $Url
    $parts = $out -split '\|', 2
    return @{ Code = $parts[0]; Location = $parts[1] }
}

Write-Host "[1] Root URL (not logged in)..." -ForegroundColor Yellow
$r1 = Get-HttpCodeAndLocation "$base/"
if ($r1.Code -eq "302" -and $r1.Location -match "login") {
    Write-Host "    PASS - 302 -> $($r1.Location)" -ForegroundColor Green
} else {
    Write-Host "    FAIL - code $($r1.Code) location $($r1.Location)" -ForegroundColor Red
}

Write-Host "[2] Dashboard (not logged in)..." -ForegroundColor Yellow
$r2 = Get-HttpCodeAndLocation "$base/dashboard/"
if ($r2.Code -eq "302" -and $r2.Location -match "login") {
    Write-Host "    PASS - 302 -> $($r2.Location)" -ForegroundColor Green
} else {
    Write-Host "    FAIL - code $($r2.Code) location $($r2.Location)" -ForegroundColor Red
}

Write-Host "[3] Login rate limit (6 wrong passwords for qahead)..." -ForegroundColor Yellow
$htmlFile = Join-Path $env:TEMP "qa_login_page.html"
curl.exe -s "$base/accounts/login/" -o $htmlFile | Out-Null
if (-not (Test-Path $htmlFile) -or (Get-Item $htmlFile).Length -lt 100) {
    Write-Host "    FAIL - cannot load login page. Is runserver running?" -ForegroundColor Red
    exit 1
}
$html = Get-Content $htmlFile -Raw
$csrf = $null
if ($html -match 'name="csrfmiddlewaretoken"\s+value="([^"]+)"') { $csrf = $Matches[1] }
elseif ($html -match 'name=''csrfmiddlewaretoken''\s+value=''([^'']+)''') { $csrf = $Matches[1] }
if (-not $csrf) {
    Write-Host "    FAIL - CSRF token not found on login page" -ForegroundColor Red
    exit 1
}

$locked = $false
for ($i = 1; $i -le 6; $i++) {
    $respFile = Join-Path $env:TEMP "qa_login_resp_$i.html"
    curl.exe -s -b $cookieJar -c $cookieJar `
        -H "Referer: $base/accounts/login/" `
        --data-urlencode "username=qahead" `
        --data-urlencode "password=wrong-$i" `
        --data-urlencode "csrfmiddlewaretoken=$csrf" `
        -o $respFile `
        "$base/accounts/login/"
    $resp = Get-Content $respFile -Raw -ErrorAction SilentlyContinue
    if ($resp -match "Too many failed login attempts") {
        Write-Host "    Attempt ${i}: LOCKED (rate limit)" -ForegroundColor Magenta
        $locked = $true
    } else {
        Write-Host "    Attempt ${i}: rejected (invalid credentials)" -ForegroundColor DarkYellow
    }
}

if ($locked) {
    Write-Host "    PASS - lockout triggered" -ForegroundColor Green
} else {
    Write-Host "    FAIL - lockout not triggered" -ForegroundColor Red
}

Write-Host "[4] Failed login audit log..." -ForegroundColor Yellow
Push-Location $projectRoot
$countRaw = python manage.py shell -c "from documents.models import ActivityLog; print(ActivityLog.objects.filter(action='login_failed').count())"
Pop-Location
$count = [int]($countRaw.Trim())
Write-Host "    login_failed rows in database: $count"
if ($count -gt 0) {
    Write-Host "    PASS - failures are logged" -ForegroundColor Green
} else {
    Write-Host "    FAIL - no login_failed rows" -ForegroundColor Red
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
if (Test-Path $cookieJar) { Remove-Item $cookieJar -Force }
