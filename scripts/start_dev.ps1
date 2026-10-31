# Start Veritas AI for development: infrastructure in Docker, the rest in their own windows.
# Usage (from the project root, in PowerShell):   .\scripts\start_dev.ps1

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Keep downloads beside the checkout, respecting any existing cache configuration.
$cacheRoot = Join-Path (Split-Path -Parent $root) "cache"
if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $cacheRoot "huggingface" }
if (-not $env:PADDLE_PDX_CACHE_HOME) { $env:PADDLE_PDX_CACHE_HOME = Join-Path $cacheRoot "paddlex" }
if (-not $env:NLTK_DATA) { $env:NLTK_DATA = Join-Path $cacheRoot "nltk_data" }

Write-Host "Starting PostgreSQL, Redis and n8n (Docker Desktop must be running)..."
docker compose up -d
if (-not $?) { Write-Host "Docker failed. Is Docker Desktop open?" -ForegroundColor Red; exit 1 }

$python = Join-Path $root ".venv\Scripts\python.exe"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Veritas API'; & '$python' -m uvicorn backend.main:app --port 8000" -WorkingDirectory $root
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Veritas worker'; & '$python' -m backend.worker" -WorkingDirectory $root
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Veritas dashboard'; npm run dev" -WorkingDirectory (Join-Path $root "frontend")

Write-Host ""
Write-Host "Dashboard:  http://localhost:5173"
Write-Host "API docs:   http://localhost:8000/docs"
Write-Host "n8n:        http://localhost:5678"
Write-Host "Close the three new windows to stop the app; 'docker compose stop' stops the rest."
