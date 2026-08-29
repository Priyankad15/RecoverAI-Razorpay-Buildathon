"""Health-check endpoint used to verify the API is up and reachable."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "RecoverAI API"}
