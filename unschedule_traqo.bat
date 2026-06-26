@echo off
:: unschedule_traqo.bat — removes the two Traqo Task Scheduler tasks.
schtasks /delete /tn "traqo_monitor" /f 2>nul && echo [OK] traqo_monitor removed || echo [WARN] traqo_monitor not found
schtasks /delete /tn "traqo_scan"    /f 2>nul && echo [OK] traqo_scan removed    || echo [WARN] traqo_scan not found
