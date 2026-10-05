@echo off
title pysswhl backend (FastAPI)
cd /d "%~dp0backend"
echo ==========================================
echo  Backend starting: http://127.0.0.1:8000
echo  API docs:         http://127.0.0.1:8000/docs
echo  Stop: Ctrl+C  (or just close this window)
echo ==========================================
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
pause
