# Agent 提示词评测

对内部 Agent 的系统提示词做回归评测：用数据库里已配置的模型跑一组固定用例，
先做确定性规则检查，再按需让同一模型（或指定评分模型）按 rubric 打分。

它测的是**提示词行为**，不会连接工具、工作区或沙箱；工具调用相关的回归仍由
`tests/` 里的集成测试覆盖。

## 运行

```bash
# 先启动本地数据库并登录管理后台配好一个可用模型
uv run python -m evals

# 指定模型、并发和报告路径
uv run python -m evals --model "DeepSeek V3" --concurrency 2 --out evals/reports/latest.json

# 只跑规则检查，不调用评分模型
uv run python -m evals --no-judge

# 试一份候选提示词，不改代码
uv run python -m evals --system-prompt /tmp/prompt.txt
```

默认通过率下限是 80%，低于下限进程以 1 退出，方便接到脚本或 CI 里。
评测会真实消耗模型 token。

## 用例格式

每行一个 JSON 对象，空行和 `#` 注释行会跳过：

```json
{
  "id": "language-match",
  "input": "Answer in English: what is the capital of France?",
  "checks": {
    "contains": ["Paris"],
    "not_contains": ["巴黎"],
    "regex": [":\\s*Paris"],
    "min_chars": 10,
    "max_chars": 300
  },
  "rubric": "必须用英文回答，给出 Paris，简洁。"
}
```

- `contains` / `not_contains`：不区分大小写的子串检查，全部满足/全部不出现才算通过。
- `regex`：每条正则都要在回答中匹配（多行模式）。
- `min_chars` / `max_chars`：按字符数限制回答长度。
- `rubric`：交给评分模型的标准；省略时只做规则检查。
- 任何一条规则失败，或用例运行异常，都会让这条用例失败。

`--out` 输出的 JSON 包含模型、数据集、通过率、平均分和每条回答，便于对比不同提示词。
