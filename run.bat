@echo off
REM ====================================================================
REM JobScouting - one-click manual launch
REM Double-click: opens the WEB APP in the browser (upload CV -> automation -> report).
REM For a ready profile, from the terminal:  run.bat profiles\other.toml
REM Onboarding/scoring in the terminal (no browser):  python main.py --cli
REM ====================================================================

cd /d "%~dp0"

echo ============================================
echo   JOBSCOUTING - start %DATE% %TIME%
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo Install Python 3.11+ or add it to PATH.
    echo.
    pause
    exit /b 1
)

if "%~1"=="" (
    python main.py
) else (
    python main.py --profile "%~1"
)
set EXITCODE=%errorlevel%

echo.
if %EXITCODE% neq 0 (
    echo [ERROR] main.py exited with code %EXITCODE%.
    echo Check the messages above ^(.env keys, network, rate limit, profile^).
    echo.
    pause
    exit /b %EXITCODE%
)

echo ============================================
echo   DONE - report in report.md (history in reports\)
echo ============================================

if exist "report.md" start "" "report.md"

echo.
pause
