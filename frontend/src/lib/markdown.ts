import MarkdownIt from "markdown-it";
import hljs from "highlight.js/lib/common";

const md = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
  highlight: (code, lang) =>
    lang && hljs.getLanguage(lang) ? hljs.highlight(code, { language: lang }).value : "",
});

const builtin = md.validateLink.bind(md);
md.validateLink = (url) => builtin(url) && /^(\/|https?:|mailto:|tel:)/i.test(url.trim());

/** 围栏代码块套一层 .code-frame：语言标签 + 展开/复制，按钮靠 MarkdownText 的事件委托响应。 */
const EXPAND_ICON =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>';

md.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index];
  const language = token.info.trim().split(/\s+/)[0];
  const highlighted = md.options.highlight?.(token.content, language, "") ?? "";
  const code = highlighted || md.utils.escapeHtml(token.content);
  return (
    `<div class="code-frame"><div class="code-bar">` +
    `<span class="code-lang">${md.utils.escapeHtml(language || "text")}</span>` +
    `<button type="button" class="code-btn code-expand" title="在侧边展开" aria-label="在侧边展开代码">${EXPAND_ICON}</button>` +
    `<button type="button" class="code-btn code-copy">复制</button></div>` +
    `<pre><code>${code}</code></pre></div>`
  );
};

/** 上下文/产物里的 <resource/> 标签转成可点下载的占位：点击由 MarkdownText 统一委托。 */
const RESOURCE_TAG =
  /<resource\s+storage_key="([^"]+)"\s+original_name="([^"]+)"(?:\s+mime_type="([^"]*)")?\s*\/>/g;

const DOWNLOAD_ICON =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>';

export const renderMarkdown = (text: string): string =>
  md.render(
    text.replace(
      RESOURCE_TAG,
      (_tag, key: string, name: string) =>
        `<span class="file-link" data-file-id="${md.utils.escapeHtml(key)}"` +
        ` data-name="${md.utils.escapeHtml(name)}" role="button" tabindex="0">` +
        `📄 ${md.utils.escapeHtml(name)}${DOWNLOAD_ICON}</span>`,
    ),
  );
