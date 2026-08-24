<#
    Запуск локального стенда «Компас» под Windows.

    Проверяет базу, окружение и порт, накатывает миграции и поднимает сервер.
    Использование:
        .\start.ps1                 обычный запуск
        .\start.ps1 -Restart        освободить порт, если сервер уже запущен
        .\start.ps1 -Port 8001      другой порт
        .\start.ps1 -LocalOnly      только этот компьютер, без доступа по сети
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Restart,
    [switch]$LocalOnly
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# без этого русский текст в консоли Windows превращается в кракозябры
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$service = 'postgresql-x64-15'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$listenHost = '0.0.0.0'
if ($LocalOnly) { $listenHost = '127.0.0.1' }

function Write-Step($text)  { Write-Host "  $text" }
function Write-Ok($text)    { Write-Host "  $text" -ForegroundColor Green }
function Write-Warn($text)  { Write-Host "  $text" -ForegroundColor Yellow }
function Write-Fail($text)  { Write-Host "  $text" -ForegroundColor Red }

Write-Host ""
Write-Host "Компас - запуск локального стенда" -ForegroundColor Cyan
Write-Host ""

# 1. База данных -------------------------------------------------------------
$postgres = Get-Service -Name $service -ErrorAction SilentlyContinue
if ($null -eq $postgres) {
    Write-Warn "Служба $service не найдена."
    Write-Step "Если PostgreSQL установлен под другим именем, проверьте: Get-Service *postgres*"
} elseif ($postgres.Status -ne 'Running') {
    Write-Step "PostgreSQL остановлена, запускаю..."
    try {
        Start-Service $service
        Start-Sleep -Seconds 2
        Write-Ok "PostgreSQL запущена."
    } catch {
        Write-Fail "Не хватило прав на запуск службы."
        Write-Step "Откройте PowerShell от имени администратора и выполните:"
        Write-Step "    Start-Service $service"
        exit 1
    }
} else {
    Write-Ok "PostgreSQL работает."
}

# 2. Виртуальное окружение ---------------------------------------------------
if (-not (Test-Path $python)) {
    Write-Fail "Не найдено окружение .venv"
    Write-Step "Создайте его один раз:"
    Write-Step "    python -m venv .venv"
    Write-Step "    .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
Write-Ok "Окружение .venv на месте."

# 3. Настройки ---------------------------------------------------------------
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Warn "Файл .env создан из .env.example - заполните пароль базы и ключ OpenRouter."
}

# 4. Порт --------------------------------------------------------------------
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    if ($Restart) {
        $busy | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            try { Stop-Process -Id $_ -Force } catch { }
        }
        Start-Sleep -Seconds 1
        Write-Ok "Прежний сервер на порту $Port остановлен."
    } else {
        Write-Warn "Порт $Port уже занят - сервер, похоже, работает."
        Write-Step "Откройте http://localhost:$Port/"
        Write-Step "Чтобы перезапустить: .\start.ps1 -Restart"
        exit 0
    }
}

# 5. Миграции ----------------------------------------------------------------
# Alembic и uvicorn пишут журнал в поток ошибок, а при 'Stop' PowerShell 5.1
# считает это сбоем команды. Поэтому вокруг внешних программ режим мягкий.
$ErrorActionPreference = 'Continue'

Write-Step "Проверяю схему базы..."
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Миграции не прошли - смотрите текст ошибки выше."
    Write-Step "Частая причина: в .env неверный пароль базы или не создана база kompas."
    exit 1
}
Write-Ok "Схема базы актуальна."

# 6. Запуск ------------------------------------------------------------------
Write-Host ""
Write-Host "  Приложение:      http://localhost:$Port/" -ForegroundColor Cyan
Write-Host "  Кабинет педагога http://localhost:$Port/static/teacher.html" -ForegroundColor Cyan
Write-Host "  Документация API http://localhost:$Port/docs" -ForegroundColor Cyan
if (-not $LocalOnly) {
    $lan = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($lan) { Write-Host "  По сети:         http://${lan}:$Port/" -ForegroundColor Cyan }
}
Write-Host ""
Write-Host "  Остановить - Ctrl+C. Пока окно открыто, сервер работает." -ForegroundColor DarkGray
Write-Host ""

& $python -m uvicorn app.main:app --host $listenHost --port $Port
