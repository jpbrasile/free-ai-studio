@echo off
rem Double-cliquez ce fichier pour mettre Free AI Studio a jour.
rem Il recupere la derniere version puis reconstruit les conteneurs.
cd /d "%~dp0"
echo.
echo  === Mise a jour de Free AI Studio ===
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\mettre-a-jour.ps1"
echo.
if errorlevel 1 (
  echo  La mise a jour a echoue. Le detail est au-dessus.
) else (
  echo  Termine. Rouvrez http://localhost:8010/studio
)
echo.
pause
