@echo off
chcp 65001 >nul
for /f "delims==" %%v in ('set QODER 2^>nul') do if /i not "%%v"=="QODER_PERSONAL_ACCESS_TOKEN" set "%%v="
set "ELECTRON_RUN_AS_NODE="
echo Qoder CLI login - a browser window will open, please authorize.
"%USERPROFILE%\.qoder\bin\qodercli\qodercli.exe" login
echo.
echo Done. You can close this window.
pause
