@echo off
title BIG - Verificacion de reportes de cliente

REM ============================================================
REM  Corre los chequeos del cierre del factsheet y el pitch book.
REM
REM  Uso:
REM     verificar_reportes.bat              -> el deck mas reciente
REM     verificar_reportes.bat Agosto       -> el de un mes puntual
REM     verificar_reportes.bat Agosto -d    -> con la salida completa
REM
REM  Tarda unos 7 segundos. No consume tokens: es todo local.
REM
REM  Un "REVISAR" NO es que se rompio algo: es que hay que mirar
REM  antes de mandar. "ROTO" si seria un error del script.
REM ============================================================

cd /d "C:\Users\lmonp\OneDrive\Desktop\Code\big-dashboard"

set MES=
set DETALLE=

if not "%~1"=="" (
    if "%~1"=="-d" (set DETALLE=--detalle) else (set MES=--mes %~1)
)
if not "%~2"=="" (
    if "%~2"=="-d" set DETALLE=--detalle
)

python scripts\verificar_reportes.py %MES% %DETALLE%
set RC=%ERRORLEVEL%

echo.
if %RC%==0 (
    echo ------------------------------------------------------------
    echo   Todo limpio. Igual conviene abrir los renders y mirar las
    echo   tortas y barras dibujadas a mano: ningun chequeo las ve.
    echo ------------------------------------------------------------
) else (
    echo ------------------------------------------------------------
    echo   Hay cosas para revisar. Ver el resumen de arriba.
    echo ------------------------------------------------------------
)
echo.
pause
