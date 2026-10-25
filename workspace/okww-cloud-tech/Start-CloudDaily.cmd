@echo off
setlocal
set "OKWW_INSTALLED_RUNTIME=%USERPROFILE%\Documents\GameAutomation\ok-ww\data\apps\ok-ww\working"
set "OKWW_PYTHON=%USERPROFILE%\Documents\GameAutomation\ok-ww\data\apps\ok-ww\python\python.exe"
if not exist "%OKWW_PYTHON%" (
  echo Installed OK-WW Python was not found. See CLOUD_PROBE.md.
  pause
  exit /b 1
)
set "PYTHONPATH=%OKWW_INSTALLED_RUNTIME%"
set "PYTHONIOENCODING=utf-8"
rem Default is offline. Explicit arguments are required for a later live session.
"%OKWW_PYTHON%" -u "%~dp0main_cloud_daily.py" %*
pause
endlocal
