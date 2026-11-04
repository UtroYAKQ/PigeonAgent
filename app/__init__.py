"""PigeonAgent 后端包。

这里只做一件事：在 LiteLLM 被导入之前关掉它的远程价格表拉取。
LiteLLM 默认会去 raw.githubusercontent.com 下载 model_prices_and_context_window.json，
内网或受限网络下会退化成三次重试（约 9 秒）才回落到本地备份，直接拖慢服务启动。
"""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
