@echo off
rem Free AI Studio : saisir une cle dans .env sans qu'elle s'affiche.
rem Pour les cles que les pages Cles du Studio ne prennent pas.
title Free AI Studio - saisir une cle
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\saisir-cle.ps1"
echo.
pause
