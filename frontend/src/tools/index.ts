import { askUserQuestion } from "./askUserQuestion";
import { openHtmlPreview } from "./openHtmlPreview";
import { registerTool } from "./registry";

// 新增前端工具只改这里：注册一个 handler，面板和请求都不用动
registerTool(openHtmlPreview);
registerTool(askUserQuestion);

export * from "./registry";
