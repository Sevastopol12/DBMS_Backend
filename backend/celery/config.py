import os
from kombu import Queue, Exchange
from dotenv import load_dotenv

load_dotenv()

broker_url = os.getenv("BROKER_URL")
result_backend = os.getenv("BROKER_URL")

task_queues = (
    Queue("default"),
    Queue("transform", Exchange(type="direct"), routing_key="utils.transform"),
    Queue("populate", Exchange(type="direct"), routing_key="client.populate"),
)

task_create_missing_queues = True

task_routes = {
    "backend.celery.tasks.transform.transform": {"queue": "transform"},
    "backend.celery.tasks.populate": {"queue": "populate"},
}

imports = "backend.celery.tasks"
