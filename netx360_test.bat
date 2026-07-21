@echo off
cd /d "%~dp0"
echo ============================================
echo   TEST MANUAL NetX360+
echo ============================================
echo.
python scripts\netx360_manual_test.py
echo.
pause
