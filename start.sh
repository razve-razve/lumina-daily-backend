#!/bin/sh
# Single worker — APScheduler (advice generation + notifications) must run in
# exactly one process. Multiple workers would fire the same cron jobs N times,
# causing duplicate notifications and conflicting DB writes.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
