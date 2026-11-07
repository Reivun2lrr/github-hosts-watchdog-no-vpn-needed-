@echo off
REM GitHub Hosts Keeper launcher - auto elevates to administrator
REM v2: install both scheduled tasks, then let the watchdog hand over to a
REM      windowless elevated supervisor (no console window to keep open).

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

echo Registering main task + watchdog task...
%PY% github_hosts_keeper.py --install-task

echo Running watchdog handover (cleans legacy daemon, starts elevated supervisor)...
%PY% github_hosts_keeper.py --watchdog
if errorlevel 1 (
    echo [WARN] Watchdog recovery did not confirm a healthy supervisor.
    echo Falling back to foreground daemon (keep this window open).
    %PY% github_hosts_keeper.py --daemon
)

echo.
echo Check status anytime with:  py -3 github_hosts_keeper.py --status
pause
