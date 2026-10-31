@echo off
cd /d "%~dp0"
echo Starting hardware-only console. No robot is connected automatically.
".venv\Scripts\python.exe" -m uvicorn edge_hub.hardware_agent:create_agent --factory --host 127.0.0.1 --port 8000 --no-access-log
pause
