import logging
import uvicorn

from fastapi import FastAPI

from backend.api import router
from backend.config import add_logger


add_logger()
logger = logging.getLogger(__name__)


app = FastAPI()
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6969, log_config=None)
