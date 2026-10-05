@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher topilmadi. Python 3.11 yoki yangirog'ini o'rnating.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo .env yaratildi. Uni ochib BOT_TOKEN va ADMIN_ID ni to'ldiring.
) else (
    echo .env mavjud, o'zgartirilmadi.
)

echo.
echo O'rnatish tugadi. Sozlamalarni to'ldirgach run.bat ni ishga tushiring.
exit /b 0
