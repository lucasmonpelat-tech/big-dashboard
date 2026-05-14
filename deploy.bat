@echo off
title BIG Dashboard - Deploy a GitHub Pages

echo.
echo ============================================================
echo   BIG Dashboard - Deploy a GitHub Pages
echo ============================================================
echo.

cd /d "C:\Users\lmonp\OneDrive\Desktop\Code\big-dashboard"

echo [1/5] Validando consistencia de datos...
python scripts\validate_data.py
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   DEPLOY ABORTADO - el validador encontro errores de datos
    echo   Revisa los [X] de arriba antes de deployar.
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)
echo.

echo [2/5] Verificando cambios pendientes...
git status --short
echo.

echo [3/5] Agregando archivos...
git add .
echo.

echo [4/5] Creando commit...
for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm"') do set DATETIME=%%a

git commit -m "update: %DATETIME%"
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   Sin cambios para commitear - ya esta actualizado
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 0
)
echo.

echo [5/5] Pusheando a GitHub...
git push
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   ERROR al pushear - revisar conexion o credenciales
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [OK] DEPLOY EXITOSO - Fer ve los cambios en 1-2 minutos
echo.
echo   URL publico:
echo   https://lucasmonpelat-tech.github.io/big-dashboard/
echo ============================================================
echo.
pause
