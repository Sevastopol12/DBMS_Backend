import uvicorn
from fastapi import FastAPI
from backend.api.routes import fetch_router, upload_router
from backend.api.resources import api_lifespan


app = FastAPI(lifespan=api_lifespan)

# Upload
app.include_router(upload_router, prefix="/upload/v1")
app.include_router(fetch_router, prefix="/fetch/v1")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6969, log_config=None)
