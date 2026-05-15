#!/bin/bash
# Start Celery worker for evaluation queue
# This worker processes evaluation tasks asynchronously

echo "Starting Celery eval worker..."
echo "Queue: eval_queue"
echo "Concurrency: 2"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 -m celery -A app.workers worker \
  -Q eval_queue \
  --concurrency=2 \
  --loglevel=info \
  --pool=solo
