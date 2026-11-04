export type PanelTabType = 'html' | 'markdown' | 'code'

export interface PanelTab {
  id: string
  sessionId: string
  type: PanelTabType
  title: string
  content: string
  language?: string
  sourceId?: string
}

export type PanelTabInput = Omit<PanelTab, 'id'>
