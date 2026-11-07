/* common 领域类型。 */

export type UUID = string

export interface TokenUsage {
  requests: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  total_tokens: number
}
