import os

from kombu import Exchange, Queue

from .settings import SweepSettings

broker_url = os.getenv("BROKER_URL")
broker_connection_retry_on_startup = True
result_backend = os.getenv("BROKER_URL")
beat_scheduler = "redbeat.RedBeatScheduler"
redbeat_redis_url = os.getenv("BROKER_URL")

task_queues = (
    Queue("default"),
    Queue("transform", Exchange(type="direct"), routing_key="utils.transform"),
    Queue("compute_metrics", Exchange(type="direct"), routing_key="client.populate"),
    Queue("maintenance", Exchange(type="direct"), routing_key="utils.maintenance"),
)

task_create_missing_queues = True

task_routes = {
    "backend.worker.tasks.transform.transform": {"queue": "transform"},
    "backend.worker.tasks.compute.compute_metrics": {"queue": "compute_metrics"},
    "backend.worker.tasks.sweep.transform_sweep": {"queue": "maintenance"},
}

_settings = SweepSettings.from_env()

# Redis-backed RedBeat avoids the default file scheduler on multi-replica workers.
beat_schedule = {
    "compute-metrics-every-30-min": {
        "task": "backend.worker.tasks.compute.compute_metrics",
        "schedule": _settings.compute_interval_seconds,
        "options": {"expires": _settings.compute_interval_seconds},
    },
    "transform-sweep-every-8h": {
        "task": "backend.worker.tasks.sweep.transform_sweep",
        "schedule": _settings.sweep_interval_seconds,
        "options": {"expires": _settings.sweep_interval_seconds},
    }
}

imports = "backend.worker.tasks"
