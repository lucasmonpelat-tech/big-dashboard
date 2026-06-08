@echo off
REM ============================================================
REM  Pampa BIG Analyzer — Launcher
REM ============================================================
REM
REM  Arranca un servidor HTTP local en el puerto 8765 sirviendo
REM  el directorio big-dashboard/ y abre el analyzer en Chrome.
REM
REM  El HTML necesita HTTP (no file://) para poder cargar el
REM  script ./data/funds_metadata.js que tiene los lookup
REM  tables (CURRENCY_EXPOSURE, CURRENT_YIELD, etc.).
REM
REM  Cuando termines, cerra esta ventana para apagar el server.
REM ============================================================

cd /d "%~dp0"

echo.
echo  ============================================================
echo   Pampa BIG Analyzer
echo  ============================================================
echo.
echo   Servidor local iniciando en http://localhost:8765
echo   Abriendo analyzer en Chrome...
echo.
echo   Cuando termines, cerra esta ventana (Ctrl+C o X)
echo.
echo  ============================================================
echo.

REM Abrir Chrome en background (sin esperar)
start "" "http://localhost:8765/pampa-big-analyzer.html"

REM Iniciar el server (bloqueante - mantiene la ventana abierta)
python -m http.server 8765
