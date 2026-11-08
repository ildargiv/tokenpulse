@echo off
rem TokenPulse monitor without title bar and border (same arguments as start-monitor.bat).
rem Move the window by its top strip; close with Alt+F4. To bring the frame back: python frameless.py --restore
set "TP_FRAMELESS=1"
call "%~dp0start-monitor.bat" %*
where python >nul 2>nul && (start "" /b python "%~dp0frameless.py") || echo Python not found: the frame stays.
