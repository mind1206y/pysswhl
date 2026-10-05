@echo off
title pysswhl frontend (Vite)
cd /d "%~dp0frontend"
echo ==========================================
echo  Frontend starting: http://localhost:5173
echo  Stop: Ctrl+C  (or just close this window)
echo ==========================================
call npm run dev
pause
