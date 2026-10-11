@echo off
echo ============================================================
echo   Starting Google Chrome for Uniflow (Single Browser Mode)
echo ============================================================
echo.
echo This starts Chrome with remote debugging on port 9222 so that
echo localhost:3000, Google Classroom, Claude, and your University
echo Portal ALL run in the EXACT SAME browser window!
echo.

set CHROME_BIN=""
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME_BIN="C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME_BIN="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME_BIN="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if %CHROME_BIN%=="" (
    echo [ERROR] Google Chrome was not found in standard directories.
    echo Please install Chrome or update the path in this script.
    pause
    exit /b 1
)

:: Check if Chrome is already running without remote debugging port
tasklist /FI "IMAGENAME eq chrome.exe" 2>NUL | find /I /N "chrome.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo [NOTICE] An existing Chrome instance was detected.
    echo Closing existing Chrome processes so remote debugging can bind to port 9222...
    taskkill /F /IM chrome.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
)

start "" %CHROME_BIN% --remote-debugging-port=9222 --profile-directory="Profile 23" http://localhost:3000
echo Google Chrome launched on port 9222 using your actual "School" student profile!
echo All your tabs, Claude logins, and Google accounts are fully preserved in this window!

