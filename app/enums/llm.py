from enum import StrEnum


# 取值与 Pydantic AI 的 provider 模块保持一致
class ThinkingLevel(StrEnum):
    """模型支持的思考挡位，取值与 Pydantic AI 的 `thinking` 设置一致。"""

    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ImageProvider(StrEnum):
    """图片生成供应商。都走 OpenAI Images 兼容协议，差别在网关地址与模型名。

    通义万相、百度、混元用的是异步任务或自有签名协议，不在这一版里，
    硬塞进来只会让用户配出一个永远调不通的模型。
    """

    OPENAI = "openai"
    ARK = "ark"
    DASHSCOPE = "dashscope"
    ZHIPU = "zhipu"
    SILICONFLOW = "siliconflow"
    CUSTOM = "custom"


class ImageProtocol(StrEnum):
    """LiteLLM 的图片调用协议；取值就是它内部的 provider route。

    `openai` 之外的协议还需要各自专属参数（azure 要 api-version、bedrock 要
    区域与签名），当前只把值传下去，不额外补参数。
    """

    OPENAI = "openai"
    AZURE = "azure"
    BEDROCK = "bedrock"
    GEMINI = "gemini"
    FAL_AI = "fal_ai"
    STABILITY = "stability"
    VERTEX_AI = "vertex_ai"
    OPENROUTER = "openrouter"


class LlmProvider(StrEnum):
    ALIBABA = "alibaba"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    BEDROCK = "bedrock"
    BEDROCK_MANTLE = "bedrock_mantle"
    CEREBRAS = "cerebras"
    COHERE = "cohere"
    CRUSOE = "crusoe"
    CUSTOM = "custom"
    DEEPSEEK = "deepseek"
    FIREWORKS = "fireworks"
    GITHUB = "github"
    GITHUB_COPILOT = "github_copilot"
    GOOGLE = "google"
    GOOGLE_CLOUD = "google_cloud"
    GROQ = "groq"
    HEROKU = "heroku"
    HUGGINGFACE = "huggingface"
    LITELLM = "litellm"
    META = "meta"
    MISTRAL = "mistral"
    MOONSHOTAI = "moonshotai"
    NEBIUS = "nebius"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    OVHCLOUD = "ovhcloud"
    SAMBANOVA = "sambanova"
    SNOWFLAKE = "snowflake"
    SYSTEM_ONE = "system_one"
    TOGETHER = "together"
    TYPESAFE = "typesafe"
    VERCEL = "vercel"
    VLLM = "vllm"
    XAI = "xai"
    ZAI = "zai"
