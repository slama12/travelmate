# Script de démarrage local TravelMate (sans Docker Desktop requis)
$ErrorActionPreference = "Stop"

Write-Host "=== TravelMate : Migration Alembic & Seed Initial ===" -ForegroundColor Cyan
Push-Location "$PSScriptRoot\backend"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m app.core.seed

Write-Host "=== Démarrage de l'API FastAPI sur http://localhost:8000 ===" -ForegroundColor Green
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
Pop-Location
