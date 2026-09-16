@echo off
chcp 65001 >nul
setlocal
set NV_DESKTOP_ROOT=
set NV_DESKTOP_DATA=
set ELECTRON_RUN_AS_NODE=
start "" /D "%~dp0release\Seqara-v0.8.0-demo.1" "%~dp0release\Seqara-v0.8.0-demo.1\有序 Seqara.exe"
endlocal
