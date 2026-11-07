/* config 领域类型。 */



/* --------------------------------- app config -------------------------------- */

export type ConfigValueType = 'string' | 'secret' | 'int' | 'float' | 'bool'
export type ConfigSource = 'database' | 'environment' | 'default'

export interface AppConfigItem {
  key: string
  category: string
  category_label: string
  label: string
  description: string | null
  value_type: ConfigValueType
  is_secret: boolean
  choices: string[] | null
  value: string | null
  has_value: boolean
  source: ConfigSource
  sort_order: number
}

export interface AppConfigList {
  items: AppConfigItem[]
  total: number
}
