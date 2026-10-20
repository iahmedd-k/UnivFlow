@echo off
echo ============================================================
echo   Starting Google Chrome for Uniflow (Azure Optimized)
echo ============================================================
echo.
echo This starts Chrome with remote debugging on port 9222 so that
echo localhost:3000, Google Classroom, Claude, and your University
echo Portal ALL run in the EXACT SAME browser window!
echo.
echo Optimized for Azure (2 vCPU, 8GB): GPU via ANGLE + Memory limits
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

:: CLEAN STALE LOCKS
if exist "%UNIFLOW_PROFILE%\SingletonLock" del "%UNIFLOW_PROFILE%\SingletonLock"
if exist "%UNIFLOW_PROFILE%\SingletonSocket" del "%UNIFLOW_PROFILE%\SingletonSocket"
if exist "%UNIFLOW_PROFILE%\SingletonCookie" del "%UNIFLOW_PROFILE%\SingletonCookie"

:: LAUNCH WITH GPU (ANGLE) + MEMORY LIMITS + PRELOADED EXTENSION
start "" "%CHROME_BIN%" ^
  --load-extension="%~dp0extension" ^
  --user-data-dir="%UNIFLOW_PROFILE%" ^
  --remote-debugging-port=9222 ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-allow-origins=* ^
  --restore-last-session ^
  --start-maximized ^
  --use-gl=angle ^
  --enable-gpu-rasterization ^
  --enable-zero-copy ^
  --ignore-gpu-blocklist ^
  --enable-features=VaapiVideoDecoder,CanvasOopRasterization ^
  --disable-background-timer-throttling ^
  --disable-renderer-backgrounding ^
  --disable-features=CalculateNativeWinOcclusion ^
  --js-flags=--max-old-space-size=512 ^
  --max_old_space_size=512 ^
  --memory-pressure-off ^
  --disable-breakpad ^
  --disable-component-update ^
  --disable-background-networking ^
  --disable-sync ^
  --disable-default-apps ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-dev-shm-usage ^
  http://localhost:3000

echo.
echo Uniflow Chrome launched (Azure optimized) on port 9222 with its persistent app profile.
echo Sign in to Claude, Google, or your University portal in this window the first time.
