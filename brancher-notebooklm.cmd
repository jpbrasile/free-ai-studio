@echo off
rem Free AI Studio : brancher NotebookLM par une connexion Google, rien a copier.
rem Le Studio doit tourner (demarrer.cmd).
title Free AI Studio - brancher NotebookLM
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\brancher-notebooklm.ps1"
echo.
pause
