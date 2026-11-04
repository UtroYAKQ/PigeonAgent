# PigeonAgent Web

PigeonAgent 的 Web 客户端：Vue 3 + TypeScript + Vite，对话与后端 FastAPI / AG-UI 流式协议完整对接。

## 技术栈

- Vue 3（`<script setup>`）+ TypeScript + Vite
- Pinia 状态管理，Vue Router 路由
- axios（自动续期 access token）
- Tailwind CSS v4 + shadcn-vue（Reka UI）+ ai-elements-vue
- lucide 图标，Geist / Geist Mono 字体
- markstream-vue + Shiki（流式 Markdown 与代码高亮）
- @vueuse/core（滚动、媒体查询、本地状态）

## 本地运行

```bash
npm install

# 真实后端（默认代理到 http://127.0.0.1:8000）
npm run dev

# mock 后端（代理到 http://127.0.0.1:8100）
npm run dev -- --mode mock
```

也可以从仓库根目录直接启动前后端：

```bat
scripts\dev-mock.cmd
scripts\dev-real.cmd
```

## 构建

```bash
npm run build
npm run preview
```

## 设置页

侧栏底部的齿轮进入 `/settings/:section?`。页面采用左侧可搜索分组导航 + 右侧分组卡片的布局：

- 通用（仅当存在工作区公用默认时显示）：管理员设置公用默认，个人设置优先覆盖，不能被公用默认反向覆盖。
- 个人：快捷键、对话偏好、账号；普通成员也能看到并使用。
- 站点 / 联网搜索 / 沙箱 / 邮箱 / 文件：管理员维护的 `app_configs`，密钥只显示是否已配置。
  生效优先级：数据库 > 环境变量 > 代码默认；数据库只保存显式覆盖。
- 模型管理：供应商使用 shadcn Select（常用 / 其他分组）；思考挡位按模型手动添加，有官方文档的厂商提供一键预设。
- 归档：在设置页内打开只读预览（`/settings/archive/:sessionId`），复用工作台对话组件完整展示思维链、工具步骤、媒体和来源，不会跳转到工作区；可恢复或删除。
- 外观：主题偏好；用户菜单里保留同一份入口。
- 账号：修改显示名称、更新密码、退出登录。
- 平台管理（仅管理员）：概览、用户管理、会话管理、操作日志；管理员写操作会留下审计记录。
## 环境变量

| 文件 | 变量 | 说明 |
| --- | --- | --- |
| `.env.development` | `VITE_PROXY_TARGET` | 真实后端地址，默认 `http://127.0.0.1:8000` |
| `.env.mock` | `VITE_PROXY_TARGET` | mock 后端地址，默认 `http://127.0.0.1:8100` |
| 任意 | `VITE_API_BASE_URL` | API 前缀，默认 `/api/v1` |

浏览器请求始终走同源 `/api/v1`，由 Vite 代理转发，避免 CORS 并让 SSE 保持简单。

## 目录

```text
src/
├── api/             # 按资源拆分的后端接口封装
├── components/
│   ├── chat/        # 会话、输入框、消息、思维链、附件等
│   ├── ai-elements/ # ai-elements-vue registry 组件
│   ├── ui/          # shadcn-vue 基础组件
│   └── brand/       # 品牌标识
├── composables/     # 滚动跟随等组合式逻辑
├── lib/             # axios / SSE / Markdown / 工具展示与格式化
├── router/          # 登录守卫与会话路由
├── stores/          # auth / chat / ui
├── types/           # API、run item、AG-UI 事件类型
└── views/           # 登录注册、会话工作台
```

## 已对接的能力

- 邮箱密码登录、注册、邮箱验证码、token 自动续期与失效退出
- 会话列表、分组管理、最近会话、搜索、重命名、归档/恢复、删除
- 会话未读状态点：run 完成自动标记，打开会话即清除
- 模型列表与切换（新会话默认模型、会话内模型）；管理员可在输入框的模型菜单中新增/编辑模型
- 模型思考挡位：按模型配置可选挡位，选择结果随会话保存并下发给后端
- 语音输入：调用浏览器 SpeechRecognition API，识别结果直接写入输入框
- 发送消息、SSE 流式回复、停止生成、断线重连、刷新后恢复进行中的 run
- AG-UI 事件：文本、推理、工具调用/结果、用量
- 思维链：推理过程、工具调用步骤、可展开的代码/终端/JSON/媒体输出（不再展示工具结果表格）
- Markdown（列表、表格、引用、代码块）、Shiki 高亮、长代码折叠、复制代码
- 分支：重新生成、编辑提问、版本切换（前后箭头）
- 图片/视频/文档上传、鉴权取图、文件下载、附件预览
- 消息操作：复制、朗读、点赞/点踩（本地）、本轮与整会话 token 用量
- 交互卡片：后端审批卡、外部结果补填；预览调用自动续跑，恢复后的内容并回同一轮消息
- 侧栏面板：每次 `ui_open_html_preview` 调用都会在右侧分割面板新增一个 tab；桌面端可拖动调整宽度，面板只保留 tab 与关闭操作
- Markdown 代码块支持在侧栏展开查看，后续可继续扩展更多内容类型
- 输入框编辑：点击消息的编辑按钮后在底部输入框继续编辑，原消息的图片/视频/文件会一并展示，可取消并恢复原草稿
- 联网搜索：输入框内开启「联网」，后端提供 DeepSeek Search / Fetch 工具（需配置 `DEEPSEEK_API_KEY`）
- 新对话 Flight Field：点阵风场、鸽子半调水印、漂浮几何、日期眉题与轨道 logo；输入框居中，发送时以共享元素动画滑落到聊天底部，支持减少动态效果
- 浅色/深色/跟随系统，移动端侧栏，滚动到最新

## Mock 交互演示

mock 后端会把这些词映射成不同的工具场景，方便验收卡片：

- `审批` 或 `触发审批`：后端审批卡
- `预览一个 HTML 页面`：前端预览工具 + 右侧面板
- `混合卡片`：审批 + 外部结果混合同一批
- `调用一个外部查询`：外部结果补填
- 开启「联网」后发送含「搜索」或「天气」的消息：mock 搜索结果与工具步骤

真实联网能力需要后端环境变量：

```bash
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_API_BASE=https://api.deepseek.com
```

后端实现位于 `app/agents/tools/web.py`，使用 DeepSeek 的 `POST /v1/tools/search` 与 `POST /v1/tools/fetch`；未配置 key 时前端联网开关会保持禁用。
