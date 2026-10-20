@echo off
echo ============================================================
echo   Creating 1-Click Uniflow Desktop Shortcut
echo ============================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "EXT_DIR=%SCRIPT_DIR%extension"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Uniflow Companion Chrome.lnk"

set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_BIN (
    echo [ERROR] Google Chrome was not found.
    pause
    exit /b 1
)

:: Use PowerShell to create a desktop shortcut with --load-extension
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%CHROME_BIN%'; $s.Arguments = '--load-extension=\"%EXT_DIR%\" http://localhost:3000'; $s.Description = 'Launch Chrome with Uniflow Extension'; $s.Save()"

echo.
echo [SUCCESS] Created shortcut on your Desktop:
echo "%SHORTCUT_PATH%"
echo.
echo When you double-click that shortcut, your normal Chrome opens
echo with the Uniflow Academic Companion pre-installed automatically!
echo No Developer Mode or manual folder loading needed.
echo.
