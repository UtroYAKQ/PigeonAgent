import AskUserQuestionForm from "../components/AskUserQuestionForm.vue";
import AskToolCard from "../components/AskToolCard.vue";
import { allAnswered, readForm, readQuestions, toPayload } from "./askResult";
import type { ManualTool, ToolPayload } from "./registry";

const questionsOf = (item: ToolPayload) => readQuestions(item.argsParsed);

export const askUserQuestion: ManualTool = {
  name: "ui_ask_user_question",
  description:
    "在需要用户做选择时调用，问题会替换输入框展示成一张答题卡。" +
    "一次调用可以问 1-4 个问题，全部答完才提交，不要把同一轮的分叉拆成多次调用。" +
    "每个问题的选项文案要自解释、互斥；multi_select 表示该题可多选；" +
    "用户始终可以自己描述或跳过，所以不必为兜底多加选项。" +
    "回执是 answers 数组，按顺序对应你问的每个问题。",
  parameters: {
    type: "object",
    properties: {
      questions: {
        type: "array",
        description: "要一起问的问题，1-4 条",
        items: {
          type: "object",
          properties: {
            question: { type: "string", description: "问题原文，一句话说清在决定什么" },
            options: {
              type: "array",
              description: "候选项，2-6 个最好读；更多也能展示，列表会自己滚，不要为此拆题",
              items: {
                type: "object",
                properties: {
                  label: { type: "string", description: "选项文案" },
                  description: { type: "string", description: "对这一项的一句补充" },
                },
                required: ["label"],
              },
            },
            multi_select: { type: "boolean", description: "是否允许多选，默认单选" },
          },
          required: ["question", "options"],
        },
      },
    },
    required: ["questions"],
  },
  form: AskUserQuestionForm,
  card: AskToolCard,
  execute: "manual",
  isReady: (value, item) => allAnswered(readForm(value, questionsOf(item).length)),
  toResult: (value, item) => {
    const questions = questionsOf(item);
    return toPayload(questions, readForm(value, questions.length));
  },
};
