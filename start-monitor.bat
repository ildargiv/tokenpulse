@echo off
rem TokenPulse: monitor in its own app window (Microsoft Edge or Chrome, no tabs or address bar).
rem   start-monitor.bat                               this computer, http://127.0.0.1:8787
rem   start-monitor.bat http://192.168.31.30:8787     a server on the network
rem   start-monitor.bat http://192.168.31.30:8787 mini   compact strip from the start
rem   start-monitor.bat http://192.168.31.30:8787 full crt    skin: pulse, crt, paper, neon, mono
chcp 65001 >nul
set "SERVER=%~1"
if "%SERVER%"=="" set "SERVER=http://127.0.0.1:8787"
if /i not "%SERVER:~0,4%"=="http" set "SERVER=http://%SERVER%"
set "SKIN="
if not "%~3"=="" set "SKIN=skin=%~3"
set "URL=%SERVER%/?%SKIN%"
set "SIZE=380,850"
if /i "%~2"=="mini" (
  set "URL=%SERVER%/?mini=1&%SKIN%"
  set "SIZE=380,150"
)
set "PROFILE=%LOCALAPPDATA%\TokenPulse\app"
set "BROWSER="
for %%P in ("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe") do (
  if not defined BROWSER if exist %%P set "BROWSER=%%~P"
)
if not defined BROWSER (
  echo Edge or Chrome not found, opening the default browser.
  start "" "%URL%"
  exit /b 0
)
start "" "%BROWSER%" --app="%URL%" --window-size=%SIZE% --user-data-dir="%PROFILE%" --no-first-run
