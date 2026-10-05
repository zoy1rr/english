@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Muhit topilmadi. Avval setup.bat ni ishga tushiring.
    exit /b 1
)

if not exist ".env" (
    echo .env topilmadi. Avval setup.bat ni ishga tushiring.
    exit /b 1
)

".venv\Scripts\python.exe" bot.py
set "BOT_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Bot jarayoni yakunlandi. Exit code: %BOT_EXIT_CODE%
pause
exit /b %BOT_EXIT_CODE%
