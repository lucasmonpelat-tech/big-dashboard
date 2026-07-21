@echo off
cd /d "%~dp0"
echo ============================================
echo   TEST AUTOMATION NetX360+ (con OTP Gmail)
echo ============================================
echo.
echo Este test:
echo   1) Abre Chrome visible
echo   2) Autocompleta user + pass
echo   3) Detecta pagina OTP
echo   4) Lee el OTP de tu Gmail
echo   5) Lo mete solo
echo.
echo NO tenes que hacer NADA. Solo mirar.
echo.
pause
python dashboard_v2\ingest\netx360_auto.py --headed
echo.
pause
