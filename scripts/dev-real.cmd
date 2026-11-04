@echo off
rem One-click real env: Postgres + S3 from .env, real model backend (:8000) + web (:5173).
rem Keep this file ASCII-only: cmd.exe misparses UTF-8 in batch files.
setlocal
cd /d "%~dp0.."

if not exist ".env" (
  echo [error] .env is missing: copy .env.example to .env and fill in DATABASE_URL / S3 / model settings.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [setup] installing backend dependencies ...
  uv sync --extra dev
  if errorlevel 1 goto :error
)
if not exist "frontend\node_modules" (
  echo [setup] installing frontend dependencies ...
  pushd frontend
  npm install
  if errorlevel 1 (popd & goto :error)
  popd
)

start "PigeonAgent backend :8000" /d "%CD%" cmd /k "uv run uvicorn app.main:app --reload --port 8000"
start "PigeonAgent web :5173" /d "%CD%\frontend" cmd /k "npm run dev"

echo.
echo   web     http://127.0.0.1:5173
echo   backend http://127.0.0.1:8000/docs
echo   first run: uv run alembic upgrade head
exit /b 0

:error
echo [error] startup failed, check the output above.
exit /b 1
