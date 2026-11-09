@echo off
REM ============================================================
REM  One-click GitHub direct connect (manual user action only).
REM  1) trigger one watchdog access check in the background
REM  2) open github.com in the default browser
REM  No background task ever opens a page by itself.
REM  The desktop copy falls back to the project folder when it is
REM  not stored next to github_hosts_keeper.py.
REM ============================================================
cd /d "%~dp0"
if not exist "github_hosts_keeper.py" cd /d "%USERPROFILE%\WorkBuddy\2026-10-12-17-35-49"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    set "PY=pythonw"
) else (
    set "PY=python"
)
start "" /B %PY% github_hosts_keeper.py --watchdog
start "" /B %PY% github_hosts_keeper.py --open
