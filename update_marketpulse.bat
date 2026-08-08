@echo off

echo ==========================================
echo       MarketPulse NSE Data Update
echo ==========================================

cd /d D:\Dashboard\nse-dashboard

echo.
echo [1/4] Fetching NSE data...
echo.

python src\backend\fetch_nse.py

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: NSE data fetch failed.
    pause
    exit /b 1
)

IF NOT EXIST "public\corporate-actions.json" (
    echo.
    echo ERROR: corporate-actions.json not found.
    pause
    exit /b 1
)

echo.
echo [2/4] NSE data updated successfully.
echo.

echo [3/4] Updating GitHub...
echo.

git add public\corporate-actions.json

git diff --cached --quiet

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo No data changes detected.
    echo Nothing to commit.
    pause
    exit /b 0
)

git commit -m "Update NSE corporate actions data"

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Git commit failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Pushing to GitHub...
echo.

git push origin main

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Git push failed.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo      MarketPulse Update Successful
echo ==========================================

echo.
echo NSE data fetched
echo JSON updated
echo GitHub updated
echo Vercel deployment triggered
echo.

pause