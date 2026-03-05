from app.core.routers.health import router as health_router
from app.core.routers.topics import router as topics_router
from app.core.routers.documents import router as documents_router

__all__ = ["health_router", "topics_router", "documents_router"]
