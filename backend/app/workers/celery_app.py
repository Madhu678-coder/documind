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
        "app.workers.openkb_tasks.*": {"queue": "default"},
        "app.workers.eval_tasks.*": {"queue": "eval_queue"},
        "app.workers.maintenance_tasks.*": {"queue": "default"},
    },
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "default.dlq": {"exchange": "default.dlq", "routing_key": "default.dlq"},
        "eval_queue": {"exchange": "eval_queue", "routing_key": "eval_queue"},
    },
)

# Explicitly import all task modules so Celery registers them on worker startup.
# Without this, tasks added after the initial celery_app creation are not discovered.
celery_app.autodiscover_tasks([
    "app.workers.tree_tasks",
    "app.workers.index_tasks",
    "app.workers.wiki_tasks",
    "app.workers.graph_tasks",
    "app.workers.openkb_tasks",
    "app.workers.eval_tasks",
    "app.workers.maintenance_tasks",
])
