@echo off
REM ============================================================
REM  Manual entry point - the ONLY way this project opens a GitHub page.
REM  Double-click this file to open github.com in your default browser.
REM  Nothing is opened automatically: no scheduled task, no login
REM  autostart, no daemon, no watchdog ever calls --open.
REM  Hosts maintenance keeps running in the background as before,
REM  so the page loads normally whenever you choose to open it.
REM ============================================================

cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% github_hosts_keeper.py --open
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to open the page. See github_hosts_keeper.log for details.
    pause
)
