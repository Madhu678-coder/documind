"""Celery application factory."""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "documind",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.tree_tasks.*": {"queue": "default"},
        "app.workers.index_tasks.*": {"queue": "default"},
        "app.workers.wiki_tasks.*": {"queue": "default"},
        "app.workers.graph_tasks.*": {"queue": "default"},
        "app.workers.eval_tasks.*": {"queue": "eval_queue"},
        "app.workers.maintenance_tasks.*": {"queue": "default"},
    },
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "default.dlq": {"exchange": "default.dlq", "routing_key": "default.dlq"},
        "eval_queue": {"exchange": "eval_queue", "routing_key": "eval_queue"},
    },
)
