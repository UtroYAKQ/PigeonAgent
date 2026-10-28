import type {
  DisplayBlock,
  InterruptKind,
  InterruptView,
  Item,
  PendingInterrupt,
  ResultFile,
  ResultMedia,
  RunApprovalRequestItem,
  RunCallRequestItem,
  RunCustomItem,
  RunErrorItem,
  RunFileItem,
  RunImageItem,
  RunItem,
  RunResourceItem,
  RunTextItem,
  RunThinkingItem,
  RunToolCallItem,
  RunToolResultItem,
  RunVideoItem,
  SessionRun,
  ToolItem,
  Usage,
} from "../types";

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** item_codec.content_to_json 存下来的媒体结构：{"media": "binary"|"image-url"|..., ...}。 */
interface StoredMedia {
  media: string;
  url?: string;
  data?: string;
  media_type?: string;
}

const MEDIA_LABEL: Record<string, string> = {
  "image-url": "图片",
  "video-url": "视频",
  "audio-url": "音频",
  "document-url": "文档",
  binary: "附件",
};

function storedMedia(value: unknown): StoredMedia | null {
  if (!isObject(value) || typeof value.media !== "string") return null;
  return value as unknown as StoredMedia;
}

function storedMediaUrl(media: StoredMedia): string {
  if (media.url) return media.url;
  if (!media.data) return "";
  return `data:${media.media_type ?? "application/octet-stream"};base64,${media.data}`;
}

/** 工具结果里的图片/视频要直接渲染，不能把 base64 当文本塞进卡片。 */
function resultMedia(content: unknown): ResultMedia[] {
  const values = Array.isArray(content) ? content : [content];
  const media: ResultMedia[] = [];
  for (const value of values) {
    const item = storedMedia(value);
    if (!item) continue;
    const url = storedMediaUrl(item);
    if (!url) continue;
    const kind = item.media_type ?? "";
    if (item.media === "video-url" || kind.startsWith("video/")) {
      media.push({ type: "video", url, mediaType: item.media_type ?? null });
    } else if (item.media === "image-url" || kind.startsWith("image/")) {
      media.push({ type: "image", url, mediaType: item.media_type ?? null });
    }
  }
  return media;
}

/** 工具发布/返回的可下载文件：认 storage_key + name 这两个字段的数据形状。 */
function resultFiles(content: unknown): ResultFile[] {
  const values = Array.isArray(content) ? content : [content];
  const files: ResultFile[] = [];
  for (const value of values) {
    if (!isObject(value)) continue;
    const key = value.storage_key;
    const name = value.name;
    if (typeof key === "string" && typeof name === "string") {
      files.push({
        storageKey: key,
        name,
        size: typeof value.size === "number" ? value.size : null,
      });
    }
  }
  return files;
}

/** 结果卡的一次读取：媒体交给图片渲染，文件给下载 chip，纯占位文本就不再重复一行。 */
export function resultView(content: unknown): {
  text: string;
  media: ResultMedia[];
  files: ResultFile[];
} {
  const media = resultMedia(content);
  const files = resultFiles(content);
  const text = contentText(content);
  const rest = text.replace(/\[(图片|视频|音频|文档|附件)\]/g, "").trim();
  // 文件引用本身没有可读正文：只渲染下载 chip，不把 JSON 铺在卡片里
  const hide = files.length > 0 || (media.length > 0 && !rest);
  return { text: hide ? "" : text, media, files };
}

export function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  const single = storedMedia(content);
  if (single) return `[${MEDIA_LABEL[single.media] ?? "附件"}]`;
  if (Array.isArray(content)) {
    const parts = content
      .map((part) => {
        if (typeof part === "string") return part;
        const media = storedMedia(part);
        if (media) return `[${MEDIA_LABEL[media.media] ?? "附件"}]`;
        if (isObject(part)) {
          if (typeof part.text === "string") return part.text;
          if (part.type === "image") return "[图片]";
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("\n");
  }
  if (content == null) return "";
  return JSON.stringify(content, null, 2);
}

export function toolArgText(args: unknown): {
  raw: string;
  parsed: Record<string, unknown> | null;
} {
  if (typeof args === "string") {
    try {
      const parsed = JSON.parse(args) as unknown;
      return {
        raw: JSON.stringify(parsed, null, 2),
        parsed: isObject(parsed) ? parsed : null,
      };
    } catch {
      return { raw: args, parsed: null };
    }
  }
  if (args == null) return { raw: "", parsed: null };
  return {
    raw: JSON.stringify(args, null, 2),
    parsed: isObject(args) ? args : null,
  };
}

function mergeUsage(
  base: Usage | null | undefined,
  next: Usage | null | undefined,
): Usage | null {
  if (!base) return next ?? null;
  if (!next) return base;
  return {
    input_tokens: Number(base.input_tokens ?? 0) + Number(next.input_tokens ?? 0),
    output_tokens: Number(base.output_tokens ?? 0) + Number(next.output_tokens ?? 0),
    cache_read_tokens:
      Number(base.cache_read_tokens ?? 0) + Number(next.cache_read_tokens ?? 0),
    cache_write_tokens:
      Number(base.cache_write_tokens ?? 0) + Number(next.cache_write_tokens ?? 0),
    requests: Number(base.requests ?? 0) + Number(next.requests ?? 0),
  };
}

function hasUsage(usage: Usage | null | undefined): usage is Usage {
  if (!usage) return false;
  return (
    Number(usage.input_tokens ?? 0) +
      Number(usage.output_tokens ?? 0) +
      Number(usage.cache_read_tokens ?? 0) +
      Number(usage.cache_write_tokens ?? 0) >
    0
  );
}

function mediaUrl(item: RunImageItem | RunVideoItem): string {
  if (item.url) return item.url;
  if (!item.data) return "";
  return `data:${item.media_type ?? "application/octet-stream"};base64,${item.data}`;
}

function userUiItem(item: RunItem): Item | null {
  if (item.type === "text") {
    const text = item as RunTextItem;
    if (!text.text.trim()) return null;
    return {
      type: "text",
      id: `text:${text.id}`,
      text: text.text,
      role: "user",
      status: "done",
    };
  }
  if (item.type === "image" || item.type === "video") {
    const media = item as RunImageItem | RunVideoItem;
    const url = mediaUrl(media);
    // 落库只存 file_id：新数据走文件拉取，老数据仍用 data base64
    if (!url && !media.file_id) return null;
    if (item.type === "image") {
      return {
        type: "image",
        id: `image:${item.id}`,
        url,
        fileId: media.file_id ?? null,
        mediaType: media.media_type ?? null,
        alt: media.alt ?? null,
      };
    }
    return {
      type: "video",
      id: `video:${item.id}`,
      url,
      fileId: media.file_id ?? null,
      mediaType: media.media_type ?? null,
      alt: media.alt ?? null,
    };
  }
  if (item.type === "resource") {
    const resource = item as RunResourceItem;
    return {
      type: "resource",
      id: `resource:${item.id}`,
      storageKey: resource.storage_key,
      name: resource.name,
      mediaType: resource.media_type,
      size: resource.size ?? null,
    };
  }
  return null;
}

function addText(block: DisplayBlock, text: string, itemId: string): void {
  if (!text.trim()) return;
  const last = block.items[block.items.length - 1];
  if (last?.type === "text") {
    last.text += text;
    return;
  }
  block.items.push({
    type: "text",
    id: `text:${itemId}`,
    text,
    role: "assistant",
    status: "done",
  });
}

/** 一个 turn 的回答跨多个 run（resume/decision）时合并到同一个回答块。 */
function ensureAssistant(
  run: SessionRun,
  blocks: DisplayBlock[],
  byAnswer: Map<string, DisplayBlock>,
  lastUserRunId: string | null,
): DisplayBlock {
  const answerTo = lastUserRunId ?? run.id;
  const existing = byAnswer.get(answerTo);
  if (existing) {
    if (!existing.runIds.includes(run.id)) existing.runIds.push(run.id);
    return existing;
  }
  const block: DisplayBlock = {
    id: `assistant:${answerTo}`,
    role: "assistant",
    items: [],
    status: run.status === "running" ? "streaming" : "done",
    runIds: [run.id],
    runId: run.id,
    answerTo,
  };
  blocks.push(block);
  byAnswer.set(answerTo, block);
  return block;
}

function applyToolResult(
  item: RunToolResultItem,
  tools: Map<string, ToolItem>,
): void {
  const tool = tools.get(item.tool_call_id);
  if (!tool) return;
  const failed = ["failed", "denied", "interrupted", "retried"].includes(
    item.outcome,
  );
  const view = resultView(item.content);
  tool.status = failed ? "error" : "done";
  tool.result = {
    status: failed ? "error" : "ok",
    content: view.text,
    error: failed ? view.text : null,
    media: view.media,
    files: view.files,
  };
  const kind = tool.interrupt?.kind;
  if (item.outcome === "denied") {
    tool.interrupt = { kind: "approval", status: "denied" };
  } else if (kind === "approval") {
    tool.interrupt = { kind: "approval", status: "approved" };
  } else if (kind === "call") {
    tool.interrupt = { kind: "call", status: "resolved" };
  }
}

export function projectUserBlock(run: SessionRun): DisplayBlock | null {
  const items = run.content
    .filter((item) => {
      if (!item.display) return false;
      if (item.type === "text") return (item as RunTextItem).role === "user";
      if (item.type === "image" || item.type === "video") {
        return (item as RunImageItem | RunVideoItem).role === "user";
      }
      if (item.type === "resource") return (item as RunResourceItem).role === "user";
      return false;
    })
    .map(userUiItem)
    .filter((item): item is Item => item !== null);
  if (items.length === 0) return null;
  return {
    id: `user:${run.id}`,
    role: "user",
    items,
    status: "done",
    created_at: run.created_at,
    runIds: [run.id],
    runId: run.id,
    parentRunId: run.parent_run_id,
    branch: run.branch ?? null,
  };
}

export interface ThreadView {
  blocks: DisplayBlock[];
  pending: InterruptView[];
}

/**
 * 一次扫描同时产出消息块和未决批次，两者不会各扫一遍、也不会互相走样。
 * 工具卡跨 run 合并：resume run 的 tool_result 要回填到原 run 的 tool_call 上。
 */
export function deriveThread(
  runs: SessionRun[],
  options: { excludeRunId?: string | null } = {},
): ThreadView {
  const blocks: DisplayBlock[] = [];
  const tools = new Map<string, ToolItem>();
  const byAnswer = new Map<string, DisplayBlock>();
  const calls = new Map<
    string,
    { name: string; args: string; argsParsed: Record<string, unknown> | null }
  >();
  const resolved = new Set<string>();
  const meta = new Map<string, Record<string, unknown>>();
  /** 工具调用在流里的先后：待处理卡片按这个顺序排队。 */
  const order = new Map<string, number>();
  const requested: PendingInterrupt[] = [];
  const seen = new Set<string>();
  let lastUserRunId: string | null = null;
  const ordered = [...runs].sort((a, b) => a.seq - b.seq);

  for (const run of ordered) {
    if (options.excludeRunId && run.id === options.excludeRunId) continue;

    const userBlock = projectUserBlock(run);
    if (userBlock) {
      blocks.push(userBlock);
      if (run.kind === "turn") lastUserRunId = run.id;
    }

    for (const item of run.content) {
      // 请求只给工具卡声明中断类型；结论由后续 ToolResultItem 回写
      if (item.type === "approval_request" || item.type === "call_request") {
        const request = item as RunApprovalRequestItem | RunCallRequestItem;
        const kind: InterruptKind =
          item.type === "approval_request" ? "approval" : "call";
        if (item.type === "call_request") {
          const callRequest = item as RunCallRequestItem;
          for (const [callId, value] of Object.entries(callRequest.metadata ?? {})) {
            if (value && typeof value === "object" && !Array.isArray(value)) {
              meta.set(callId, value as Record<string, unknown>);
            }
          }
        }
        for (const toolCallId of request.tool_call_ids) {
          const tool = tools.get(toolCallId);
          if (tool && !tool.interrupt) {
            tool.interrupt = { kind, status: "pending" };
          }
          const key = `${request.interrupt_id}:${toolCallId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          requested.push({
            interrupt_id: request.interrupt_id,
            tool_call_id: toolCallId,
            kind,
          });
        }
        continue;
      }
      if (!item.display) continue;

      if (item.type === "tool_result") {
        resolved.add((item as RunToolResultItem).tool_call_id);
        applyToolResult(item as RunToolResultItem, tools);
        continue;
      }

      if (item.type === "text" && (item as RunTextItem).role === "user") continue;
      if (
        (item.type === "image" || item.type === "video") &&
        (item as RunImageItem | RunVideoItem).role === "user"
      ) {
        continue;
      }
      if (item.type === "resource" && (item as RunResourceItem).role === "user") continue;

      const block = ensureAssistant(run, blocks, byAnswer, lastUserRunId);

      if (item.type === "text") {
        addText(block, (item as RunTextItem).text, item.id);
      } else if (item.type === "thinking") {
        const thinking = item as RunThinkingItem;
        if (thinking.text.trim()) {
          block.items.push({
            type: "thinking",
            id: `thinking:${item.id}`,
            text: thinking.text,
            status: "done",
          });
        }
      } else if (item.type === "tool_call") {
        const call = item as RunToolCallItem;
        const args = toolArgText(call.args);
        calls.set(call.tool_call_id, {
          name: call.tool_name,
          args: args.raw,
          argsParsed: args.parsed,
        });
        if (!order.has(call.tool_call_id)) order.set(call.tool_call_id, order.size);
        const existing = tools.get(call.tool_call_id);
        if (!existing) {
          const tool: ToolItem = {
            type: "tool",
            id: `tool:${call.tool_call_id}`,
            toolCallId: call.tool_call_id,
            name: call.tool_name,
            args: args.raw,
            argsParsed: args.parsed,
            result: null,
            // 这一轮被中断时，没结果的调用就是半截的，别再显示"等待结果"
            status: run.status === "cancelled" ? "interrupted" : "ready",
            interrupt: null,
          };
          block.items.push(tool);
          tools.set(call.tool_call_id, tool);
        }
      } else if (item.type === "error") {
        const error = item as RunErrorItem;
        block.items.push({
          type: "error",
          id: `error:${item.id}`,
          message: error.message,
          code: error.code,
          retryable: error.retryable ?? false,
        });
        block.status = "error";
      } else if (item.type === "custom") {
        const payload = item as RunCustomItem;
        block.items.push({
          type: "custom",
          id: `custom:${item.id}`,
          name: payload.renderer ?? "custom",
          version: payload.version ?? 1,
          value: payload.data ?? null,
          status: "done",
        });
      } else if (item.type === "image" || item.type === "video") {
        const media = item as RunImageItem | RunVideoItem;
        const url = mediaUrl(media);
        if (!url) continue;
        if (item.type === "image") {
          block.items.push({
            type: "image",
            id: `image:${item.id}`,
            url,
            mediaType: media.media_type ?? null,
            alt: media.alt ?? null,
          });
        } else {
          block.items.push({
            type: "video",
            id: `video:${item.id}`,
            url,
            mediaType: media.media_type ?? null,
            alt: media.alt ?? null,
          });
        }
      } else if (item.type === "file") {
        // 模型产出的文件/语音：user 角色的文件在用户气泡里已经处理过，这里是助手侧
        const file = item as RunFileItem;
        block.items.push({
          type: "file",
          id: `file:${item.id}`,
          name: file.name,
          mediaType: file.media_type,
          size: file.size ?? 0,
        });
      } else if (item.type === "resource") {
        // 助手侧的产物 chip：点开就能拿回文件
        const resource = item as RunResourceItem;
        block.items.push({
          type: "resource",
          id: `resource:${item.id}`,
          storageKey: resource.storage_key,
          name: resource.name,
          mediaType: resource.media_type,
          size: resource.size ?? null,
        });
      }

    }

    const answerTo = lastUserRunId ?? run.id;
    const ownBlock = byAnswer.get(answerTo);
    if (ownBlock) {
      if (run.status === "failed") ownBlock.status = "error";
      else if (run.status === "running") ownBlock.status = "streaming";
      else if (ownBlock.status !== "error") ownBlock.status = "done";
      // 后续 run 跑完了就不算中断，别把续跑成功的回答也标成已中断
      if (run.status === "cancelled") ownBlock.interrupted = true;
      else if (run.status === "completed") ownBlock.interrupted = false;
      if (hasUsage(run.usage)) {
        ownBlock.usage = mergeUsage(ownBlock.usage, run.usage);
      }
    }
  }

  const pending = requested
    .filter((item) => !resolved.has(item.tool_call_id))
    .map((item) => {
      const call = calls.get(item.tool_call_id);
      return {
        ...item,
        name: call?.name ?? "tool",
        args: call?.args ?? "",
        argsParsed: call?.argsParsed ?? null,
        meta: meta.get(item.tool_call_id) ?? null,
      };
    })
    .sort(
      (a, b) =>
        (order.get(a.tool_call_id) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.tool_call_id) ?? Number.MAX_SAFE_INTEGER),
    );

  for (const item of pending) {
    const tool = tools.get(item.tool_call_id);
    if (tool && !tool.interrupt) {
      tool.interrupt = { kind: item.kind as InterruptKind, status: "pending" };
    }
  }

  return { blocks, pending };
}
