@echo off
echo Stopping Bitbank FastAPI Trading Server...
wsl -d Ubuntu-26.04 pkill -f tradingbot.server
echo Stopped. (Note: any open Bitbank positions still keep their native exchange stop orders.)
pause
