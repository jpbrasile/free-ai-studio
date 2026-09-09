@echo off
rem Free AI Studio : le seul fichier a double-cliquer.
rem Installe ce qui manque, demarre les services, ouvre la page.
rem Le rappeler plus tard ne casse rien : il redemarre, c'est tout.
title Free AI Studio
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\demarrer.ps1"
echo.
pause
