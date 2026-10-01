import os

from kombu import Exchange, Queue

broker_url = os.getenv("BROKER_URL")
result_backend = os.getenv("BROKER_URL")
beat_scheduler = "redbeat.RedBeatScheduler"
redbeat_redis_url = os.getenv("BROKER_URL")

task_queues = (
    Queue("default"),
    Queue("transform", Exchange(type="direct"), routing_key="utils.transform"),
    Queue("compute_metrics", Exchange(type="direct"), routing_key="client.populate"),
)

task_create_missing_queues = True

task_routes = {
    "backend.worker.tasks.transform.transform": {"queue": "transform"},
    "backend.worker.tasks.compute.compute_metrics": {"queue": "compute_metrics"},
}

# Redis-backed RedBeat avoids the default file scheduler on multi-replica workers.
beat_schedule = {
    "compute-metrics-every-30-min": {
        "task": "backend.worker.tasks.compute.compute_metrics",
        "schedule": 1800.0,
        "options": {"expires": 1800},
    }
}

imports = "backend.worker.tasks"
