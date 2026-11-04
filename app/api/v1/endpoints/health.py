import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import EnvSettingsDep, SessionDep
from app.schemas.health import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse)
async def ready(db: SessionDep, settings: EnvSettingsDep) -> ReadyResponse | JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        # 探针失败要能在日志里看出原因，不然运维只看到一个 503
        logger.exception("Readiness check failed: database ping")
        failure = ReadyResponse(status="unavailable", database="down", storage="unknown")
        return JSONResponse(status_code=503, content=failure.model_dump())
    return ReadyResponse(
        status="ok",
        database="up",
        storage="configured" if settings.s3_bucket else "disabled",
    )
