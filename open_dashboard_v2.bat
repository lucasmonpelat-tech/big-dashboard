@echo off
cd /d "%~dp0"
echo ============================================
echo   Dashboard V2 - BIG Fund
echo ============================================
echo.
echo Server: http://localhost:8765
echo Dashboard: http://localhost:8765/dashboard_v2/presentation/index.html
echo.
echo Ctrl+C para parar el server
echo.
python -m dashboard_v2.presentation.serve
