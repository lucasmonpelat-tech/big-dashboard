@echo off
cd /d "%~dp0"
echo ============================================
echo   Refresh full pipeline BIG Dashboard V2
echo ============================================
echo.
echo 1) Descarga 4 XLSX desde NetX360+ (auto-login OTP)
echo 2) Corre los 4 parsers (positions/transactions/pnl/costs)
echo 3) Escribe canonical JSONs en data/canonical/
echo.
pause

echo.
echo === STEP 1: Ingest ===
python dashboard_v2\ingest\netx360_auto.py --headed
if errorlevel 1 (
    echo.
    echo [FAIL] Ingest fallo. Ver alertas en data/_alerts/.
    pause
    exit /b 1
)

echo.
echo === STEP 2: Transform ===
python -m dashboard_v2.transform.run_all
if errorlevel 1 (
    echo.
    echo [FAIL] Transform fallo (ver validation errors arriba).
    pause
    exit /b 1
)

echo.
echo ============================================
echo   OK - Pipeline completo
echo ============================================
echo.
echo Ahora corre open_dashboard_v2.bat para verlo.
echo.
pause
