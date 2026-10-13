@echo off
echo ============================================================
echo   Starting Google Chrome for Uniflow (Single Browser Mode)
echo ============================================================
echo.
echo This starts Chrome with remote debugging on port 9222 so that
echo localhost:3000, Google Classroom, Claude, and your University
echo Portal ALL run in the EXACT SAME browser window!
echo.

set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_BIN (
    echo [ERROR] Google Chrome was not found in standard directories.
    echo Please install Chrome or update the path in this script.
    pause
    exit /b 1
)

:: Keep the automation profile separate from the user's normal Chrome data directory.
set "UNIFLOW_PROFILE=%~dp0backend\tmp\claude_browser_profile"
if not exist "%UNIFLOW_PROFILE%" mkdir "%UNIFLOW_PROFILE%"

:: Launch the persistent Uniflow profile without closing or modifying normal Chrome sessions.
start "" "%CHROME_BIN%" --user-data-dir="%UNIFLOW_PROFILE%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=* --restore-last-session --start-maximized http://localhost:3000
echo.
echo Uniflow Chrome launched on port 9222 with its persistent app profile.
echo Sign in to Claude, Google, or your University portal in this window the first time.
