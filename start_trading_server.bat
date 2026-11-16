@echo off
echo Stopping any existing trading server instance...
wsl -d Ubuntu-26.04 pkill -f tradingbot.server 2>nul
echo Starting Bitbank FastAPI Live Trading Server on http://localhost:8000 ...
start "" http://localhost:8000
wsl -d Ubuntu-26.04 bash -c "cd '/mnt/c/Users/user/Desktop/Trading bot' && python3 -u -m tradingbot.server --mode live --baseline 98874.1 --port 8000"
pause
