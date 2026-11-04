from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    auth,
    capabilities,
    configs,
    files,
    health,
    image_models,
    llm_models,
    public_shares,
    runs,
    session_groups,
    session_runs,
    sessions,
    shares,
    usage,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(capabilities.router)
router.include_router(configs.router)
router.include_router(admin.router)
router.include_router(auth.router)
router.include_router(llm_models.router)
router.include_router(image_models.router)
router.include_router(sessions.router)
router.include_router(session_groups.router)
router.include_router(session_runs.router)
router.include_router(runs.router)
router.include_router(files.router)
router.include_router(usage.router)
router.include_router(shares.router)
router.include_router(public_shares.router)
