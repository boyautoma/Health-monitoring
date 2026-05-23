@echo off
REM Sync Garmin data and push to GitHub
REM Run via Windows Task Scheduler (2x/day: 10h + 21h)

cd /d "C:\Users\Sylvain\SynologyDrive\SPORT\AppCoach"

REM Run sync
python sync_garmin.py
if errorlevel 1 (
    echo Sync failed with exit code %errorlevel%
    exit /b %errorlevel%
)

REM Pull any remote changes first
git pull --rebase --quiet

REM Commit and push data changes
git add docs/data/
git diff --staged --quiet
if errorlevel 1 (
    git commit -m "sync: Garmin data %date:~6,4%-%date:~3,2%-%date:~0,2% %time:~0,5%"
    git push
    echo Sync complete and pushed
) else (
    echo No data changes to push
)
