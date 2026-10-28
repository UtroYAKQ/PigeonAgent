/**
 * 提问工具的载荷与解析，单独放一份：工具、答题表单、历史卡共用，避免互相 import 成环。
 * 一次调用可以问多个问题，所以答案永远是数组。
 */
export interface AskOption {
  label: string;
  description: string;
}

export interface AskQuestion {
  question: string;
  options: AskOption[];
  multi: boolean;
}

export interface AskAnswer {
  selected: string[];
  note: string;
  skipped: boolean;
}

export interface AskEntry {
  question: string;
  answer: string[];
  note: string;
  skipped: boolean;
}

export interface AskResult {
  entries: AskEntry[];
  skipped: boolean;
}

export const answered = (answer: AskAnswer): boolean =>
  answer.skipped || answer.selected.length > 0 || answer.note.trim() !== "";

function optionOf(entry: unknown): AskOption | null {
  if (typeof entry === "string") {
    return entry.trim() ? { label: entry.trim(), description: "" } : null;
  }
  if (typeof entry !== "object" || entry === null) return null;
  const record = entry as Record<string, unknown>;
  const label = typeof record.label === "string" ? record.label.trim() : "";
  if (!label) return null;
  return {
    label,
    description: typeof record.description === "string" ? record.description.trim() : "",
  };
}

/**
 * 收两种形状：`questions: [...]` 和老的单问题 `question/options`。
 * 形状跑偏的条目丢掉，全丢光就退化成自由输入，不让卡片空一块。
 */
export function readQuestions(args: Record<string, unknown> | null): AskQuestion[] {
  const raw = Array.isArray(args?.questions)
    ? args.questions
    : args?.question
      ? [args]
      : [];
  return raw
    .map((entry): AskQuestion | null => {
      if (typeof entry !== "object" || entry === null) return null;
      const record = entry as Record<string, unknown>;
      const question = typeof record.question === "string" ? record.question.trim() : "";
      const options = Array.isArray(record.options)
        ? record.options.map(optionOf).filter((item): item is AskOption => item !== null)
        : [];
      if (!question && options.length === 0) return null;
      return { question, options, multi: record.multi_select === true };
    })
    .filter((item): item is AskQuestion => item !== null);
}

function answerOf(value: unknown): AskAnswer {
  const record = value as Partial<AskAnswer> | null;
  return {
    selected: Array.isArray(record?.selected)
      ? record.selected.filter((label): label is string => typeof label === "string")
      : [],
    note: typeof record?.note === "string" ? record.note : "",
    skipped: record?.skipped === true,
  };
}

/** 面板里的值是 unknown，按题数收成确定的 answers 形状。 */
export function readForm(value: unknown, count: number): AskAnswer[] {
  const raw = (value as { answers?: unknown } | null)?.answers;
  const list = Array.isArray(raw) ? raw : [];
  return Array.from({ length: count }, (_, index) => answerOf(list[index]));
}

export function allAnswered(answers: AskAnswer[]): boolean {
  return answers.length > 0 && answers.every(answered);
}

/** 回执把问题原文带上，模型不用猜顺序。 */
export function toPayload(questions: AskQuestion[], answers: AskAnswer[]): unknown {
  if (answers.length > 0 && answers.every((answer) => answer.skipped)) {
    return { skipped: true, message: "用户跳过了这次提问，稍后会在对话里说明。" };
  }
  return {
    answers: answers.map((answer, index) => ({
      question: questions[index]?.question ?? "",
      answer: answer.selected,
      ...(answer.note.trim() ? { note: answer.note.trim() } : {}),
      ...(answer.skipped ? { skipped: true } : {}),
    })),
  };
}

/** 回填给模型的内容可能是字符串；老会话里的单答案形状也认。 */
export function readAskResult(value: unknown): AskResult {
  if (typeof value === "string") {
    try {
      return readAskResult(JSON.parse(value));
    } catch {
      return { entries: [], skipped: false };
    }
  }
  const record = (value ?? {}) as Record<string, unknown>;
  if (record.skipped === true && !Array.isArray(record.answers)) {
    return { entries: [], skipped: true };
  }
  const raw = Array.isArray(record.answers)
    ? record.answers
    : record.answer || record.note
      ? [record]
      : [];
  const entries = raw
    .map((entry): AskEntry | null => {
      if (typeof entry !== "object" || entry === null) return null;
      const item = entry as Record<string, unknown>;
      const answer = Array.isArray(item.answer)
        ? item.answer.filter((label): label is string => typeof label === "string")
        : [];
      const note = typeof item.note === "string" ? item.note.trim() : "";
      const question = typeof item.question === "string" ? item.question.trim() : "";
      if (!question && answer.length === 0 && !note) return null;
      return { question, answer, note, skipped: item.skipped === true };
    })
    .filter((entry): entry is AskEntry => entry !== null);
  return { entries, skipped: record.skipped === true };
}
