@echo off
rem One-click mock env: SQLite + in-process moto S3 + fake-model backend (:8100) + web dev server (:5173).
rem Keep this file ASCII-only: cmd.exe misparses UTF-8 in batch files.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo [setup] installing backend dependencies ...
  uv sync --extra dev
  if errorlevel 1 goto :error
)
uv run python -c "import moto" >nul 2>nul
if errorlevel 1 (
  echo [setup] installing mock dependencies ...
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
echo [setup] freeing ports 8100 / 5173 ...
call :free_port 8100
call :free_port 5173

start "PigeonAgent mock backend :8100" /d "%CD%" cmd /k "uv run python scripts\mock_server.py"
start "PigeonAgent web dev :5173" /d "%CD%\frontend" cmd /k "npm run dev -- --mode mock"

echo.
echo   web          http://127.0.0.1:5173
echo   mock backend http://127.0.0.1:8100
exit /b 0

:free_port
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo [setup] stopping process %%P on port %PORT% ...
  taskkill /F /PID %%P >nul 2>nul
)
exit /b 0

:error
echo [error] startup failed, check the output above.
exit /b 1
