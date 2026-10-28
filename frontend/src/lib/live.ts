import type {
  AguiEvent,
  DisplayBlock,
  ErrorItem,
  Item,
  TextItem,
  ThinkingItem,
  ToolItem,
} from "../types";
import { contentText, resultView, toolArgText } from "./projector";

export function newLiveBlock(id = "live"): DisplayBlock {
  return {
    id,
    role: "assistant",
    items: [],
    status: "streaming",
    runIds: [],
  };
}

function cloneItems(items: Item[]): Item[] {
  return items.map((item) => ({ ...item }) as Item);
}

function textItem(block: DisplayBlock, id: string): TextItem {
  const existing = block.items.find(
    (item): item is TextItem => item.type === "text" && item.id === id,
  );
  if (existing) return existing;
  const created: TextItem = {
    type: "text",
    id,
    text: "",
    role: "assistant",
    status: "streaming",
  };
  block.items.push(created);
  return created;
}

function thinkingItem(block: DisplayBlock, id: string): ThinkingItem {
  const existing = block.items.find(
    (item): item is ThinkingItem => item.type === "thinking" && item.id === id,
  );
  if (existing) return existing;
  const created: ThinkingItem = {
    type: "thinking",
    id,
    text: "",
    status: "streaming",
  };
  block.items.push(created);
  return created;
}

function findTool(block: DisplayBlock, id: string): ToolItem | undefined {
  return block.items.find(
    (item): item is ToolItem => item.type === "tool" && item.toolCallId === id,
  );
}

/** 只有 TOOL_CALL_START 建卡；参数/结果/收尾事件找不到卡就忽略，避免和历史里的同一次调用并排出两张。 */
function toolItem(block: DisplayBlock, id: string): ToolItem {
  const existing = findTool(block, id);
  if (existing) return existing;
  const created: ToolItem = {
    type: "tool",
    id: `tool:${id}`,
    toolCallId: id,
    name: "tool",
    args: "",
    argsParsed: null,
    result: null,
    status: "streaming",
  };
  block.items.push(created);
  return created;
}

function findItem(block: DisplayBlock, id: string): Item | undefined {
  return block.items.find((item) => item.id === id);
}

/** 把一帧 AG-UI 事件折进当前临时 assistant 块；收口后仍以 entries 为准。 */
export function reduceLive(current: DisplayBlock, event: AguiEvent): DisplayBlock {
  const block: DisplayBlock = {
    ...current,
    items: cloneItems(current.items),
    status: current.status === "error" ? "error" : "streaming",
  };
  const messageId = event.messageId ?? "assistant";

  switch (event.type) {
    case "TEXT_MESSAGE_START":
      textItem(block, messageId).status = "streaming";
      break;
    case "TEXT_MESSAGE_CONTENT": {
      const item = textItem(block, messageId);
      item.text += event.delta ?? "";
      break;
    }
    case "TEXT_MESSAGE_END": {
      const item = textItem(block, messageId);
      item.status = "done";
      break;
    }
    case "REASONING_MESSAGE_START":
      thinkingItem(block, messageId).status = "streaming";
      break;
    case "REASONING_MESSAGE_CONTENT": {
      const item = thinkingItem(block, messageId);
      item.text += event.delta ?? "";
      break;
    }
    case "REASONING_MESSAGE_END": {
      thinkingItem(block, messageId).status = "done";
      break;
    }
    case "TOOL_CALL_START": {
      const callId = event.toolCallId ?? `call-${block.items.length}`;
      const item = toolItem(block, callId);
      item.name = event.toolCallName ?? item.name;
      item.status = "streaming";
      break;
    }
    case "TOOL_CALL_ARGS": {
      const item = findTool(block, event.toolCallId ?? "");
      if (item) item.args += event.delta ?? "";
      break;
    }
    case "TOOL_CALL_END": {
      const item = findTool(block, event.toolCallId ?? "");
      if (!item) break;
      const parsed = toolArgText(item.args);
      item.args = parsed.raw;
      item.argsParsed = parsed.parsed;
      item.status = "ready";
      break;
    }
    case "TOOL_CALL_RESULT": {
      // resume 轮的结果对应的那次调用已经在历史里了，这里再建一张就成双卡
      const item = findTool(block, event.toolCallId ?? "");
      if (!item) break;
      const failed = event.isError === true;
      const view = resultView(event.content);
      item.status = failed ? "error" : "done";
      item.result = {
        status: failed ? "error" : "ok",
        content: view.text,
        error: failed ? view.text : null,
        media: view.media,
        files: view.files,
      };
      break;
    }
    case "CUSTOM": {
      block.items.push({
        type: "custom",
        id: `custom:${block.items.length}`,
        name: event.name ?? "custom",
        value: event.value ?? null,
        status: "done",
      });
      break;
    }
    case "STATE_SNAPSHOT": {
      block.items.push({
        type: "custom",
        id: `state:${block.items.length}`,
        name: "state",
        value: event.snapshot ?? null,
        status: "done",
      });
      break;
    }
    case "RUN_ERROR": {
      const item: ErrorItem = {
        type: "error",
        id: "run-error",
        message: contentText(event.message ?? event.code ?? "运行失败"),
        code: event.code ?? null,
      };
      const existing = findItem(block, "run-error");
      if (existing?.type === "error") existing.message = item.message;
      else block.items.push(item);
      block.status = "error";
      break;
    }
    case "RUN_FINISHED":
      if (block.status !== "error") block.status = "done";
      break;
    default:
      break;
  }
  return block;
}
