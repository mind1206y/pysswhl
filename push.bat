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
echo Git Push - Dual Remote
echo ========================================

rem keep origin remote usable: create the bare backup repo on first run (silent)
if not exist "%BARE%" git init --bare "%BARE%" >nul 2>nul
git --git-dir="%BARE%" symbolic-ref HEAD refs/heads/main >nul 2>nul

echo [1/4] Commit changes...
git add -A
git commit -m "chore: auto backup %TS%"
if %errorlevel% equ 0 (
    echo OK
) else (
    echo Nothing to commit / commit failed
)

echo [2/4] Local backup ^(git^)...
git push origin main
if %errorlevel% neq 0 (
    echo Local backup FAILED!
    popd
    pause
    exit /b 1
)
echo OK

echo [3/4] GitHub...
git push github main:github-clean
if %errorlevel% neq 0 (
    echo GitHub push FAILED!
    popd
    pause
    exit /b 1
)
echo OK

echo [4/4] File backup...
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

echo ========================================
echo All done!
echo ========================================

popd
pause
