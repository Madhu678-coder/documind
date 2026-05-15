#!/bin/bash
# Script to restart the Celery eval worker and populate evaluations for all messages

echo "========================================="
echo "Restarting Celery Eval Worker"
echo "========================================="

# Stop existing worker
echo "Stopping existing Celery worker..."
pkill -f "celery.*eval_queue"
sleep 2

# Start new worker in background
echo "Starting Celery worker with updated code..."
cd "$(dirname "$0")"
python3 -m celery -A app.workers worker -Q eval_queue --concurrency=1 --loglevel=info --pool=solo > /tmp/celery_eval_worker.log 2>&1 &
WORKER_PID=$!
echo "Worker started with PID: $WORKER_PID"
echo "Logs: /tmp/celery_eval_worker.log"

# Wait for worker to initialize
echo "Waiting for worker to initialize..."
sleep 5

# Trigger evaluations for all missing messages
echo ""
echo "========================================="
echo "Triggering Evaluations"
echo "========================================="
python3 trigger_missing_evals.py

# Wait for evaluations to complete
echo ""
echo "Waiting for evaluations to complete (30 seconds)..."
sleep 30

# Check results
echo ""
echo "========================================="
echo "Checking Results"
echo "========================================="
python3 check_eval_data.py

echo ""
echo "========================================="
echo "Done!"
echo "========================================="
echo "Worker PID: $WORKER_PID"
echo "Worker logs: /tmp/celery_eval_worker.log"
echo ""
echo "To view worker logs in real-time:"
echo "  tail -f /tmp/celery_eval_worker.log"
echo ""
echo "To stop the worker:"
echo "  kill $WORKER_PID"
echo "  # OR"
echo "  pkill -f 'celery.*eval_queue'"
