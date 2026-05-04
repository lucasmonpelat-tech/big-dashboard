@echo off
title BIG Dashboard - Deploy a GitHub Pages

echo.
echo ============================================================
echo   BIG Dashboard - Deploy a GitHub Pages
echo ============================================================
echo.

cd /d "C:\Users\lmonp\OneDrive\Desktop\Code\big-dashboard"

echo [1/4] Verificando cambios pendientes...
git status --short
echo.

echo [2/4] Agregando archivos...
git add .
echo.

echo [3/4] Creando commit...
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value ^| find "="') do set datetime=%%a
set FECHA=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%
set HORA=%datetime:~8,2%:%datetime:~10,2%

git commit -m "update: %FECHA% %HORA%"
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

echo [4/4] Pusheando a GitHub...
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
