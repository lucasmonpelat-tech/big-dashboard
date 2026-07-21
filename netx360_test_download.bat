@echo off
cd /d "%~dp0"
echo ============================================
echo   TEST DOWNLOAD AUTOMATICO NetX360+
echo ============================================
echo.
echo Este test:
echo   1) Login automatico
echo   2) Navega Positions, Transactions, UGL, RGL
echo   3) Click icono download + opcion Excel
echo   4) Guarda los 4 XLSX en data/raw/YYYY-MM-DD/netx360/
echo.
echo Chrome se abre visible. NO tocar nada.
echo.
pause

echo.
echo Limpiando descargas previas de hoy...
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set today=%%I
if exist "data\raw\%today%\netx360\*.xlsx" del /q "data\raw\%today%\netx360\*.xlsx"

echo Corriendo automation...
echo.
python dashboard_v2\ingest\netx360_auto.py --headed
echo.
echo ============================================
echo   Resultado en: data\raw\%today%\netx360\
echo ============================================
pause
