import type {
  CompactionItem,
  ErrorItem,
  ImageItem,
  LiveRun,
  ResourceItem,
  RunStatus,
  VideoItem,
} from '@/types/api'
import type { ToolStep } from '@/lib/tools'

export interface ReasoningEntry {
  kind: 'reasoning'
  id: string
  text: string
  streaming: boolean
}

export interface ToolEntry {
  kind: 'tool'
  step: ToolStep
}

export type ChainEntry = ReasoningEntry | ToolEntry

/** 产物在正文里的统一形态；图片、视频、附件都走这一层，渲染侧不用分辨来源 */
export interface ArtifactMedia {
  id: string
  kind: 'image' | 'video' | 'file'
  /** generated = 图片工具产出；workspace = 沙箱里写的文件 */
  origin: 'generated' | 'workspace'
  mediaType: string
  fileId?: string | null
  src?: string | null
  data?: string | null
  name?: string
  size?: number
  alt?: string | null
}

export interface SourceRef {
  url: string
  icon: string | null
}

/** 历史 item 和实时 block 归一后的同一种来源；适配器只认这些形状。 */
export type TurnSource =
  | { kind: 'text'; id: string; text: string; streaming: boolean }
  | { kind: 'reasoning'; id: string; text: string; streaming: boolean }
  | { kind: 'tool'; step: ToolStep }
  | { kind: 'media'; media: ArtifactMedia }
  | { kind: 'custom'; id: string; renderer: string; data: unknown }
  | { kind: 'unsupported'; id: string; sourceKind: string }

/** 来源适配器的输出；footer 类 part 由模板归位，不参与正文分段。 */
export type TurnPart =
  | { type: 'text'; id: string; text: string; streaming: boolean }
  | { type: 'chain-entry'; id: string; entry: ChainEntry }
  | { type: 'media'; id: string; media: ArtifactMedia[]; state: 'ready' | 'pending' }
  | { type: 'attachment'; id: string; media: ArtifactMedia[] }
  | { type: 'source-link'; id: string; source: SourceRef }
  | { type: 'card'; id: string; renderer: string; data: unknown }
  | { type: 'unknown'; id: string; sourceKind: string }

export interface TextBlock {
  type: 'text'
  id: string
  text: string
  streaming: boolean
}

export interface ChainBlock {
  type: 'chain'
  id: string
  entries: ChainEntry[]
  streaming: boolean
}

export interface MediaBlock {
  type: 'media'
  id: string
  media: ArtifactMedia[]
  state: 'ready' | 'pending'
}

export interface CardBlock {
  type: 'card'
  id: string
  renderer: string
  data: unknown
}

export interface UnknownBlock {
  type: 'unknown'
  id: string
  sourceKind: string
}

export type TurnBlock = TextBlock | ChainBlock | MediaBlock | CardBlock | UnknownBlock

export interface TurnView {
  userText: string
  userImages: ImageItem[]
  userVideos: VideoItem[]
  userResources: ResourceItem[]
  blocks: TurnBlock[]
  steps: ToolStep[]
  compactions: CompactionItem[]
  liveCompaction: LiveRun['compaction']
  error: ErrorItem | null
  liveError: string | null
  liveErrorCode: string | null
  attachments: ArtifactMedia[]
  assistantText: string
  status: RunStatus | 'streaming'
  interrupted: boolean
  cancelled: boolean
  sources: SourceRef[]
}