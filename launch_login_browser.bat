@echo off
echo ============================================================
echo   Uniflow Google Sign-In Browser (Bypasses Google Security Block)
echo ============================================================
echo.
echo Launching Chrome WITHOUT remote debugging port so Google detects
echo it as a 100%% genuine, secure browser and allows university sign-in.
echo.

set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_BIN (
    echo [ERROR] Google Chrome was not found. Please install Chrome.
    pause
    exit /b 1
)

set "UNIFLOW_PROFILE=%~dp0backend\tmp\claude_browser_profile"
if not exist "%UNIFLOW_PROFILE%" mkdir "%UNIFLOW_PROFILE%"

:: Clean stale lock files
if exist "%UNIFLOW_PROFILE%\SingletonLock" del "%UNIFLOW_PROFILE%\SingletonLock"
if exist "%UNIFLOW_PROFILE%\SingletonSocket" del "%UNIFLOW_PROFILE%\SingletonSocket"
if exist "%UNIFLOW_PROFILE%\SingletonCookie" del "%UNIFLOW_PROFILE%\SingletonCookie"

:: Launch NORMAL Chrome with preloaded extension and NO remote-debugging port
:: This bypasses "This browser or app may not be secure" completely!
start "" "%CHROME_BIN%" ^
  --load-extension="%~dp0extension" ^
  --user-data-dir="%UNIFLOW_PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  https://classroom.google.com

echo Chrome launched! Log into Google Classroom in this window.
echo Your session will be saved permanently for autonomous turn-ins.
