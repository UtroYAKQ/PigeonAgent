import type {
  AdminMcpServer,
  AdminMcpServerCreatePayload,
  AdminMcpServerList,
  AdminMcpServerUpdatePayload,
  McpServerTestResult,
} from '@/types/api'
import { http } from '@/lib/http'

export const mcpServersApi = {
  async list(): Promise<AdminMcpServerList> {
    const { data } = await http.get<AdminMcpServerList>('/mcp-servers', {
      params: { limit: 200 },
    })
    return data
  },

  async create(payload: AdminMcpServerCreatePayload): Promise<AdminMcpServer> {
    const { data } = await http.post<AdminMcpServer>('/mcp-servers', payload)
    return data
  },

  async update(id: string, payload: AdminMcpServerUpdatePayload): Promise<AdminMcpServer> {
    const { data } = await http.patch<AdminMcpServer>(`/mcp-servers/${id}`, payload)
    return data
  },

  async remove(id: string): Promise<void> {
    await http.delete(`/mcp-servers/${id}`)
  },

  async test(id: string): Promise<McpServerTestResult> {
    const { data } = await http.post<McpServerTestResult>(`/mcp-servers/${id}/test`)
    return data
  },
}
