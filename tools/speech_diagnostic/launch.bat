@echo off
title SO-101 Speech Diagnostic Arena
cd /d "%~dp0"
echo =======================================================
echo Starting SO-101 Speech-to-Speech Diagnostic Arena
echo Web UI will be available at: http://127.0.0.1:7865
echo =======================================================
C:\Python311\python.exe app.py
pause
