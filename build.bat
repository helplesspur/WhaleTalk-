@echo off
rem Rebuild BiliVoiceBot.exe (requires .venv, see tutorial)
cd /d "%~dp0"
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --console --name WhaleTalk --add-data "web;web" --hidden-import qrcode.image.svg --hidden-import miniaudio --exclude-module matplotlib --exclude-module PyQt5 main.py
if errorlevel 1 (echo BUILD FAILED & pause & exit /b 1)
echo Build OK: dist\WhaleTalk.exe
pause
