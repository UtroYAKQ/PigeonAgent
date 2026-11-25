export type PanelTabType = 'html' | 'markdown' | 'code' | 'file'

export interface PanelTab {
  id: string
  sessionId: string
  type: PanelTabType
  title: string
  content: string
  language?: string
  sourceId?: string
  fileId?: string
  mediaType?: string | null
  size?: number | null
}

export type PanelTabInput = Omit<PanelTab, 'id'>
