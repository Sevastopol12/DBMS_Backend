import os
from kombu import Queue, Exchange
from dotenv import load_dotenv

load_dotenv()

broker_url = os.getenv("BROKER_URL")
result_backend = os.getenv("BROKER_URL")

task_queues = (
    Queue("default"),
    Queue("transform", Exchange("transform", type="direct"), routing_key="transform"),
)

task_create_missing_queues = True

task_routes = {
    "backend.celery.tasks.transform.transform": {"queue": "transform", "routing_key": "transform"},
}

task_acks_late = True
task_reject_on_worker_lost = True

imports = "backend.celery.tasks"
