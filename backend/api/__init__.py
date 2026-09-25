from .routes.upload import router as upload_router
from .routes.fetch import router as fetch_router

__all__ = ["upload_router", "fetch_router"]
