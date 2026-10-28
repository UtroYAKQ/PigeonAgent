OPENAI_MODEL_MODULE = "openai"
OPENAI_MODEL_PATH = f"pydantic_ai.models.{OPENAI_MODEL_MODULE}"
PREFERRED_OPENAI_MODEL = "OpenAIChatModel"

# 有专用 model 模块的 provider；其余一律走 OpenAI 兼容的 OpenAIChatModel
NATIVE_MODEL_MODULES = frozenset(
    {
        "anthropic",
        "bedrock",
        "bedrock_mantle",
        "cerebras",
        "cohere",
        "crusoe",
        "github_copilot",
        "google",
        "groq",
        "huggingface",
        "mistral",
        "openrouter",
        "snowflake",
        "system_one",
        "typesafe",
        "xai",
        "zai",
    }
)

# google_cloud 的 provider 独立，但 model 复用 google 模块
MODEL_MODULE_OVERRIDES = {"google_cloud": "google"}

# custom 走通用 OpenAI 兼容 provider，由 base_url 指定端点
PROVIDER_MODULE_OVERRIDES = {"custom": "openai"}

# 本地/自建部署可以完全没有鉴权
NO_API_KEY_REQUIRED = frozenset({"custom", "vllm"})
