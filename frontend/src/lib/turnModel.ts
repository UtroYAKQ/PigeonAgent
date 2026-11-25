/** 消息渲染的数据入口：来源归一 → 适配器 → Part → 块，见 lib/turn。 */

export type * from './turn/types'
export {
  buildTurnView,
  hasAssistantOutput,
  hasUserOutput,
  mergeTurnViews,
  projectLiveRun,
} from './turn/build'