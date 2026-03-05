from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
def health_check() -> dict:
    """Liveness probe — returns service identity and version."""
    return {
        "service": "vdr-agent",
        "status": "ok",
        "version": "0.1.0",
    }
