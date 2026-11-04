# 架构

本文只描述系统边界、一次 run 的生命周期和前端投影方式。具体实现以代码为准。

## 分层

```text
浏览器
  └─ Vue 3 客户端（frontend/src）
       ├─ REST /api/v1/*           鉴权、会话、文件、配置、管理后台
       └─ SSE /api/v1/sessions/{id}/runs/{run_id}/events

FastAPI（app/）
  ├─ api/          路由、鉴权依赖、请求校验
  ├─ services/     业务编排：run_store、run、session、usage、file、config…
  ├─ agents/       Agent 定义、turn 编排、工具
  ├─ render/       SSE 事件生产 / 消费，进程内队列或 Redis Streams
  ├─ infra/        模型、图片、对象存储、邮件适配
  ├─ sandbox/      e2b 兼容沙箱与本地工作区
  ├─ tasks/        操作日志、对象 GC 等后台任务
  └─ core/         配置、安全、异常、日志契约
```

依赖方向保持向下：`api → services → domain / models / infra`，`core` 不依赖 `api` 或 `services`。Agent 层只通过 `services` 暴露的存储与用量接口落库。

## 一次 run 的生命周期

1. **创建 run**：客户端向 `POST /sessions/{id}/runs` 提交用户消息、模型和思考挡位。`run_store.create_run` 写入 `session_runs`，并通过 `parent_run_id` 把新 run 挂到当前分支节点上。
2. **占用会话租约**：同一会话同一时间只允许一个活跃 run。数据库的 `sessions.active_run_id` 记录当前 run；配置 `REDIS_URL` 后 `RenderHub` 用 Redis `SET NX` 做跨进程互斥，租约到期可由后续请求接管。`RunRegistry` 在本进程保存取消令牌，并通过 Redis 归属键 + Pub/Sub 支持跨 worker 取消。
3. **构建上下文**：`services/run.execute_run` 沿当前分支回溯，加载 run items；存在 `CompactionItem` 时只回灌压缩点之后的内容。未决审批或外部调用所在的分支不会被压缩。
4. **流式执行**：`agents/turn.AgentTurn` 调用 Pydantic AI 的流式接口，把模型输出、思维链、工具调用、工具结果和用量转换成 AG-UI 事件；同时把有语义的片段写成 run item（`app/domain/run_items.py`）。
5. **事件分发**：`render/RenderHub` 把事件写入会话事件流。单进程使用内存队列，超出 backlog 落临时 jsonl；配置 Redis 后使用 Redis Streams，支持多 worker 和迟到消费者回放。
6. **取消与收尾**：取消请求可以在任意 worker 进入；本地有令牌就直接取消，否则先确认 Redis 归属键仍然存在，再通过 Pub/Sub 广播给持有该 run 的 worker。收到最终结果后按 `RunUsage` 增量记录用量并结算积分；取消、异常或客户端断开时，已完成模型请求的用量会通过兜底路径补记。沙箱模式下，`SandboxPool` 把远端沙箱指针写入 Redis，run 漂到其他 worker 时会 connect 同一个沙箱，工作区文件不会丢。
7. **前端投影**：`frontend/src/stores/chat.ts` 合并历史 run 与实时事件，`frontend/src/lib/turnModel.ts` 把 item 序列投影成「思维链 / 正文 / 产物」三类分段；刷新后从事件流回放或重新拉取 run 树。

## 数据模型

| 表 | 作用 |
| --- | --- |
| `users` | 账号、密码哈希、角色、邮箱验证、token 版本、偏好、积分余额 |
| `sessions` / `session_groups` | 会话、分组、归档、未读状态、活跃 run 租约 |
| `session_runs` | 对话树节点；`parent_run_id` 组成分支，items 以 JSON 持久化 |
| `file_records` / `blobs` / `upload_sessions` | 文件引用、内容寻址对象、分片上传会话 |
| `llm_models` / `image_models` | 模型、思考挡位、上下文窗口、工具能力、定价 |
| `app_configs` | 管理员可覆盖的运行时配置；密钥类值加密存储 |
| `operation_logs` | HTTP 操作日志；管理员写操作以 `kind='admin'` 记在同一张表 |
| `credit_ledgers` / `chat_request_logs` | 积分流水与逐轮请求记账 |

## 安全边界

- 所有业务接口要求 Bearer token；改密或管理员重置密码会让 `token_version` 递增，旧 token 立即失效。
- 文件按上传者隔离；HTML 等主动内容以内联下载 + `nosniff` + CSP sandbox 返回。
- 媒体直链由服务端校验归属后签名，浏览器直接从对象存储取字节；`S3_PUBLIC_ENDPOINT_URL` 必须是浏览器可达地址。
- 密钥类配置（模型 API key、SMTP 密码、沙箱 key）使用 `SECRET_KEY` 加密入库，接口只返回是否已配置。
- 操作日志对密码、token、Cookie、API key 递归脱敏；管理员写操作写入审计日志。
- `SECRET_KEY` 缺失或仍为旧示例值时应用拒绝启动；更换 `SECRET_KEY` 会导致已加密配置、分享链接和邮箱验证码失效，需要重新录入或重新签发。

## 前端

- `stores/chat.ts`：会话、run 树、SSE 连接、流式状态和重连。
- `lib/turnModel.ts`：把后端 item 投影为可渲染的分段；实时事件和历史数据走同一套投影。
- `components/chat/`：消息、思维链、工具步骤、审批/提问卡片、输入框、附件。
- `views/SettingsView.vue` 与 `views/AdminView.vue`：个人设置与平台后台，共用 console shell。
- Markdown 使用 markstream-vue + Shiki；公式和图表按需加载 KaTeX / Mermaid。
