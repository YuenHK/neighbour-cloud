@echo off
cd /d "%~dp0"
echo Keep the hardware-only console running first. Google sign-in protects this Free endpoint.
".venv\Scripts\python.exe" -m edge_hub.remote_access_runner --hardware-only --ngrok "%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe"
pause
