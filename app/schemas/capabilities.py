from pydantic import BaseModel


class ImageModelOption(BaseModel):
    """输入框图片选择器需要的最小信息；密钥、地址等管理字段不外泄。"""

    id: int
    name: str
    icon: str | None
    default_size: str
    sizes: list[str]
    max_images: int
    is_default: bool


class CapabilitiesRead(BaseModel):
    # 有凭证且平台允许；请求级开关还会再收窄一次
    web_search: bool
    # 有可用图片模型且平台允许
    image_generation: bool
    # 可选的图片模型；为空时前端不显示图片入口
    image_models: list[ImageModelOption] = []
    default_image_model_id: int | None = None
    max_upload_bytes: int
    max_image_attachments: int
    max_resource_files: int
