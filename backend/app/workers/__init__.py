from app.workers.celery_app import celery_app

# Auto-discover tasks so Celery registers them
celery_app.autodiscover_tasks([
    "app.workers.tree_tasks",
    "app.workers.eval_tasks",
    "app.workers.maintenance_tasks",
    "app.workers.index_tasks",
    "app.workers.wiki_tasks",
    "app.workers.graph_tasks",
])
