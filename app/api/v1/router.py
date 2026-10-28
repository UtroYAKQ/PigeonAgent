from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    files,
    health,
    llm_models,
    runs,
    session_groups,
    session_runs,
    sessions,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
router.include_router(llm_models.router)
router.include_router(sessions.router)
router.include_router(session_groups.router)
router.include_router(session_runs.router)
router.include_router(runs.router)
router.include_router(files.router)
