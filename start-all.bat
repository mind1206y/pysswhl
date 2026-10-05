@echo off
title pysswhl launcher
start "pysswhl-backend"  "%~dp0start-backend.bat"
start "pysswhl-frontend" "%~dp0start-frontend.bat"
timeout /t 6 /nobreak >nul
start "" http://localhost:5173
echo Two windows opened. Login: admin / admin123
