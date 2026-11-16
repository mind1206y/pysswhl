@echo off
setlocal
set "PATH=C:\Program Files\Git\cmd;%PATH%"

set "REPO=E:\pysswhl"
set "BACKUP=E:\pysswhl-backup"
set "BARE=E:\pysswhl-backup.git"

pushd "%REPO%"
if %errorlevel% neq 0 (
    echo ERROR: cannot enter %REPO%
    pause
    exit /b 1
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm:ss"') do set "TS=%%i"

echo ========================================
echo   pysswhl - Git Backup ^& Dual Push
echo   %TS%
echo ========================================
echo.

echo [1/5] Ensure local bare backup repo...
if not exist "%BARE%" (
    git init --bare "%BARE%"
    echo   created %BARE%
)
git --git-dir="%BARE%" symbolic-ref HEAD refs/heads/main >nul 2>nul
echo OK

echo.
echo [2/5] Commit changes...
set "NEWCOMMIT=0"
git add -A
git commit -q -m "chore: auto backup %TS%"
if %errorlevel% equ 0 (
    set "NEWCOMMIT=1"
    echo OK
) else (
    echo Nothing to commit ^(no file changes^)
)

echo.
echo [3/5] Local backup ^(origin: %BARE%^)...
git push origin main
if %errorlevel% neq 0 (
    echo Local backup FAILED!
    popd
    pause
    exit /b 1
)
echo OK

echo.
echo [4/5] GitHub...
git push github main:github-clean
if %errorlevel% neq 0 (
    echo GitHub push FAILED!
    popd
    pause
    exit /b 1
)
echo OK

echo.
echo [5/5] File backup ^(config / secret / db artifacts^)...
if not exist "%BACKUP%" mkdir "%BACKUP%"
copy /y backend\.env "%BACKUP%\.env" >nul 2>nul
copy /y backend\.env.example "%BACKUP%\.env.example" >nul 2>nul
copy /y backend\rsa_key.pem "%BACKUP%\rsa_key.pem" >nul 2>nul
rem .gitignore excludes db dumps / release tarballs (github 100MB limit), back them up as files
if not exist "%BACKUP%\artifacts" mkdir "%BACKUP%\artifacts"
if exist deploy\import robocopy deploy\import "%BACKUP%\artifacts" /E /NFL /NDL /NJH /NJS /NP >nul 2>nul
copy /y *.tar.gz "%BACKUP%\artifacts\" >nul 2>nul
copy /y *.sql.gz "%BACKUP%\artifacts\" >nul 2>nul
echo OK

echo.
echo ========================================
echo   All done!  %TS%
echo ========================================
if "%NEWCOMMIT%"=="1" (
    git log -1 --format="  new commit  %%h  %%s"
) else (
    git log -1 --format="  no new commit, HEAD stays at %%h"
)

popd
echo.
pause
