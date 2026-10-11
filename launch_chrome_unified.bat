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

:: Set persistent Uniflow Chrome user data directory
set UNIFLOW_PROFILE=%LOCALAPPDATA%\UniflowChromeProfile
if not exist "%UNIFLOW_PROFILE%" mkdir "%UNIFLOW_PROFILE%"

start "" %CHROME_BIN% --user-data-dir="%UNIFLOW_PROFILE%" --remote-debugging-port=21735 --remote-allow-origins=* --no-first-run --no-default-browser-check http://localhost:3000
echo Chrome launched on port 21735 with persistent profile!
echo You can now use Uniflow, the Portal, and Claude in this single window!

