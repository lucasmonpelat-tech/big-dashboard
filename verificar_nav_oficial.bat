@echo off
REM ============================================================
REM  Verificar el NAV de Lynk contra el CAV oficial de ProCapital
REM ============================================================
REM
REM  CUANDO CORRERLO: una vez por mes, justo despues de subir el CAV
REM  a la carpeta de fees. Ese es el unico momento en que hay dato
REM  nuevo para comparar.
REM
REM  QUE HACE:
REM    1. Busca el CAV mas nuevo en la carpeta de fees.
REM    2. Compara fecha por fecha contra lo que publica Lynk.
REM    3. Avisa si algun NAV no coincide con el registro oficial.
REM    4. Guarda el CAV destilado en data/cav_nav_oficial.json.
REM
REM  POR QUE EXISTE: el 14-Sep-2026 Lynk reescribio el NAV del
REM  12-Ago, un mes despues de publicarlo. Se encontro de casualidad.
REM  Esto lo detecta solo.
REM
REM  Corre LOCAL a proposito: el CAV vive en Dropbox y el cron de
REM  GitHub no lo ve.
REM ============================================================

cd /d "%~dp0"

echo.
python scripts\check_lynk_vs_cav.py --guardar --alerta "data\_alerts\lynk_vs_cav_%date:~-4%-%date:~3,2%-%date:~0,2%.json"
set RESULTADO=%ERRORLEVEL%

echo.
if %RESULTADO% NEQ 0 (
    echo ============================================================
    echo   HAY UNA DISCREPANCIA NUEVA. Leer el detalle arriba.
    echo.
    echo   El CAV manda: es el registro del agente de calculo.
    echo   Para corregirlo en el pipeline, agregar la fecha a
    echo   data\lynk_puntos_malos.json con el valor del CAV.
    echo ============================================================
) else (
    echo ============================================================
    echo   Todo coincide con el CAV oficial.
    echo ============================================================
)

echo.
echo Si cambio data\cav_nav_oficial.json, conviene commitearlo:
echo    git add data\cav_nav_oficial.json ^&^& git commit -m "chore(cav): NAV oficial del mes"
echo.
pause
