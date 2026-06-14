@echo off
setlocal
cd /d "%~dp0"

set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%CODEX_PY%" (
  echo Starting AIBL preview with Codex Python...
  "%CODEX_PY%" web_app.py
  exit /b %ERRORLEVEL%
)

echo Starting AIBL preview with system Python...
python -m pip install -r requirements.txt
python web_app.py
