@echo off
REM Creates a Desktop shortcut ("NBTC Brief") that launches the app with the BMA icon.
cd /d "%~dp0"
set "TARGET=%~dp0Start NBTC Brief.bat"
set "ICON=%~dp0bma.ico"
set "WORKDIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\NBTC Brief.lnk');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%WORKDIR%';" ^
  "$s.IconLocation='%ICON%';" ^
  "$s.WindowStyle=7;" ^
  "$s.Description='National Border Targeting Centre Brief';" ^
  "$s.Save()"
if exist "%USERPROFILE%\Desktop\NBTC Brief.lnk" ( echo. & echo  Done. An "NBTC Brief" shortcut is on your Desktop. ) else ( echo. & echo  Could not confirm the shortcut. Check that bma.ico is present. )
echo.
pause
