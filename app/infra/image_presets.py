"""图片供应商预设。

各家路径并不统一：同样是「OpenAI Images 兼容」的调用，火山方舟在
`/api/v3/images/generations`、智谱在 `/api/paas/v4/images/generations`。
所以 base_url 不能由着用户猜，选中供应商就带出正确的地址和常用尺寸，
用户只需要填 model 和 key。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import UnprocessableError
from app.enums import ImageProtocol, ImageProvider


@dataclass(frozen=True, slots=True)
class ImageProviderPreset:
    key: ImageProvider
    label: str
    # 请求协议。现在全是 openai 兼容；留给通义/百度这类异步协议扩展
    protocol: ImageProtocol
    # 空表示必须由调用方提供（自定义网关）
    base_url: str | None
    # 相对 base_url 的路径
    path: str
    # 上游模型名示例，仅用于前端 placeholder
    model_hint: str
    sizes: tuple[str, ...]
    note: str | None = None


PROVIDER_PRESETS: tuple[ImageProviderPreset, ...] = (
    ImageProviderPreset(
        key=ImageProvider.OPENAI,
        label="OpenAI",
        protocol=ImageProtocol.OPENAI,
        base_url="https://api.openai.com/v1",
        path="/images/generations",
        model_hint="gpt-image-1",
        sizes=("1024x1024", "1536x1024", "1024x1536"),
    ),
    ImageProviderPreset(
        key=ImageProvider.ARK,
        label="火山方舟（Seedream）",
        protocol=ImageProtocol.OPENAI,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        path="/images/generations",
        model_hint="doubao-seedream-4-0-250828",
        sizes=("1024x1024", "2048x1152", "1152x2048"),
        note="模型名填方舟的模型 ID，不是展示名",
    ),
    ImageProviderPreset(
        key=ImageProvider.DASHSCOPE,
        label="阿里云百炼（通义千问）",
        protocol=ImageProtocol.OPENAI,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        path="/images/generations",
        model_hint="qwen-image-3.0-pro",
        sizes=("1024x1024", "1536x1024", "1024x1536"),
        note="必须走 compatible-mode；用其他区域域名时填 https://<域名>/compatible-mode/v1",
    ),
    ImageProviderPreset(
        key=ImageProvider.ZHIPU,
        label="智谱（CogView）",
        protocol=ImageProtocol.OPENAI,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        path="/images/generations",
        model_hint="cogview-4",
        sizes=("1024x1024", "1440x720", "720x1440"),
    ),
    ImageProviderPreset(
        key=ImageProvider.SILICONFLOW,
        label="硅基流动",
        protocol=ImageProtocol.OPENAI,
        base_url="https://api.siliconflow.cn/v1",
        path="/images/generations",
        model_hint="Kwai-Kolors/Kolors",
        sizes=("1024x1024", "1024x576", "576x1024"),
    ),
    ImageProviderPreset(
        key=ImageProvider.CUSTOM,
        label="自定义 / 兼容网关",
        protocol=ImageProtocol.OPENAI,
        base_url=None,
        path="/images/generations",
        model_hint="留空则填上游模型名",
        sizes=("1024x1024",),
        note="地址填到版本前缀为止，例如 https://gateway.example.com/v1",
    ),
)

PRESET_BY_KEY: dict[str, ImageProviderPreset] = {
    preset.key.value: preset for preset in PROVIDER_PRESETS
}


def preset_of(provider: str) -> ImageProviderPreset:
    """按 key 取预设。库里存了不认识的 provider 就报错——悄悄当 OpenAI 处理，
    只会让请求打到错误的地址上，排查成本比一条 422 高得多。
    """
    preset = PRESET_BY_KEY.get(provider)
    if preset is None:
        raise UnprocessableError(f"未知的图片供应商「{provider}」")
    return preset


def _declared_base(provider: str, base_url: str | None) -> tuple[ImageProviderPreset, str]:
    """用户填的地址优先，没填用预设地址；两者都空就是配置不全。"""
    preset = preset_of(provider)
    base = (base_url or preset.base_url or "").rstrip("/")
    if not base:
        raise UnprocessableError(f"供应商「{preset.label}」需要填写接口地址")
    return preset, base


def resolve_endpoint(provider: str, base_url: str | None) -> str:
    """把「供应商 + 可能的自定义地址」拼成最终请求地址。

    已经填成完整地址（以 path 结尾）就不再重复拼接，方便直接把文档里的
    全路径粘进来。
    """
    preset, base = _declared_base(provider, base_url)
    if base.endswith(preset.path):
        return base
    return f"{base}{preset.path}"


def resolve_base_url(provider: str, base_url: str | None) -> str:
    """给 SDK 用的 base：SDK 自己会拼 `/images/generations`，这里只留前缀。

    用户如果粘了完整地址，把路径后缀剥掉，避免拼成两遍。
    """
    preset, base = _declared_base(provider, base_url)
    if base.endswith(preset.path):
        return base[: -len(preset.path)]
    return base
