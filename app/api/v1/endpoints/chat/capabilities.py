from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.schemas.model.capabilities import CapabilitiesRead, ImageModelOption
from app.schemas.run import MAX_ATTACHMENTS, MAX_RESOURCES
from app.services.model import image as image_model_service

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=CapabilitiesRead)
async def capabilities(
    user: CurrentUserDep, settings: SettingsDep, db: SessionDep
) -> CapabilitiesRead:
    # 能力 = 资源就绪（有凭证 / 有模型）且平台总闸开着；请求级开关在开 run 时再收窄一次
    image_models = await image_model_service.list_active_models(db)
    default_image_model = next(
        (model for model in image_models if model.is_default),
        image_models[0] if image_models else None,
    )
    return CapabilitiesRead(
        web_search=settings.can_use_web_search,
        image_generation=bool(image_models) and settings.feature_image_generation_enabled,
        image_models=[
            ImageModelOption(
                id=model.id,
                name=model.name,
                icon=model.icon,
                default_size=model.default_size,
                sizes=model.sizes,
                max_images=model.max_images,
                is_default=model.id == default_image_model.id if default_image_model else False,
            )
            for model in image_models
        ],
        default_image_model_id=default_image_model.id if default_image_model else None,
        max_upload_bytes=settings.max_upload_bytes,
        max_image_attachments=MAX_ATTACHMENTS,
        max_resource_files=MAX_RESOURCES,
    )
