/* model 领域类型。 */



export type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface LlmModel {
  id: number
  name: string
  provider: string
  icon: string | null
  model_name: string
  base_url: string | null
  context_window: number | null
  max_output_tokens: number | null
  compaction_threshold: number | null
  credit_input_per_1m: number | null
  credit_output_per_1m: number | null
  credit_cache_read_per_1m: number | null
  thinking_levels: ThinkingLevel[]
  supports_tools: boolean
  is_active: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface LlmModelList {
  items: LlmModel[]
  total: number
}

export interface LlmModelCreatePayload {
  name: string
  provider: string
  icon?: string | null
  model_name: string
  base_url?: string | null
  api_key?: string | null
  context_window?: number | null
  max_output_tokens?: number | null
  compaction_threshold?: number | null
  credit_input_per_1m?: number | null
  credit_output_per_1m?: number | null
  credit_cache_read_per_1m?: number | null
  thinking_levels?: ThinkingLevel[]
  supports_tools?: boolean
  is_active?: boolean
  is_default?: boolean
}

export type LlmModelUpdatePayload = Partial<LlmModelCreatePayload>

/* --------------------------------- image model ------------------------------- */

export interface ImageModel {
  id: number
  name: string
  provider: string
  protocol: string
  icon: string | null
  model_name: string
  base_url: string | null
  sizes: string[]
  default_size: string
  max_images: number
  quality: string | null
  credit_per_image: number | null
  is_active: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface ImageProviderPreset {
  key: string
  label: string
  protocol: string
  base_url: string | null
  path: string
  model_hint: string
  sizes: string[]
  note: string | null
}

export interface ImageModelList {
  items: ImageModel[]
  total: number
}

export interface ImageModelCreatePayload {
  name: string
  provider?: string
  protocol?: string
  icon?: string | null
  model_name: string
  base_url?: string | null
  api_key?: string | null
  sizes?: string[]
  default_size?: string
  max_images?: number
  quality?: string | null
  credit_per_image?: number | null
  is_active?: boolean
  is_default?: boolean
}

export type ImageModelUpdatePayload = Partial<ImageModelCreatePayload>

export interface ImageModelOption {
  id: number
  name: string
  icon: string | null
  default_size: string
  sizes: string[]
  max_images: number
  is_default: boolean
}

export interface Capabilities {
  web_search: boolean
  image_generation: boolean
  image_models: ImageModelOption[]
  default_image_model_id: number | null
  max_upload_bytes: number
  max_image_attachments: number
  max_resource_files: number
}
