@echo off
set "PATH=C:\Program Files\Git\cmd;%PATH%"

pushd E:\pysswhl
if %errorlevel% neq 0 (
    echo ERROR: cannot enter E:\pysswhl
    pause
    exit /b 1
)

echo ========================================
echo   Git Push - Dual Remote
echo ========================================
echo.

echo [1/4] Commit changes...
git add -A
git commit -m "chore: auto commit"
if %errorlevel% equ 0 (
    echo OK
) else (
    echo Nothing to commit / commit failed
)
echo.

echo [2/4] Local backup (git)...
git push origin main
if %errorlevel% neq 0 (
    echo Local backup FAILED!
    popd
    pause
    exit /b %errorlevel%
)
echo OK

echo.
echo [3/4] GitHub...
git push github main:github-clean
if %errorlevel% neq 0 (
    echo GitHub push FAILED!
    popd
    pause
    exit /b %errorlevel%
)
echo OK

echo.
echo [4/4] File backup...
if not exist "E:\pysswhl-backup" mkdir "E:\pysswhl-backup"
copy /y backend\.env "E:\pysswhl-backup\.env" >nul 2>nul
copy /y backend\.env.example "E:\pysswhl-backup\.env.example" >nul 2>nul
if %errorlevel% equ 0 echo OK

popd
echo.
echo ========================================
echo   All done!
echo ========================================
pause
