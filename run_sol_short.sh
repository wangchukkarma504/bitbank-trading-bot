#!/usr/bin/env bash
cd /home/karma/Trading-bot
nohup python3 -u manage_sol_short.py > /home/karma/Trading-bot/manage_sol_short.log 2>&1 </dev/null &
echo "Started manage_sol_short with PID $!"
sleep 2
cat /home/karma/Trading-bot/manage_sol_short.log
