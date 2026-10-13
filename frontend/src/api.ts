// Thin client for the FastAPI routes. Errors carry the backend's `detail` message.
import type {
  Approval, ApproveResult, Cash, Contributions, FeedResponse, Run, TicketsResponse,
} from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  tickets: () => request<TicketsResponse>('/api/tickets'),
  cash: () => request<Cash>('/api/cash'),
  approvals: () => request<{ count: number; requests: Approval[] }>('/api/approvals?status=pending'),
  run: (ticketId: number) => post<Run>('/api/run', { ticket_id: ticketId }),
  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),
  runs: () => request<{ runs: Run[] }>('/api/runs'),
  feed: (ticketId: number, since: number) =>
    request<FeedResponse>(`/api/events?ticket_id=${ticketId}&latest_run=true&since=${since}&limit=500`),
  contributions: (ticketId: number) => request<Contributions>(`/api/tickets/${ticketId}/contributions`),
  approve: (id: number, approvedBy: string) => post<ApproveResult>(`/api/approvals/${id}/approve`, { approved_by: approvedBy }),
  reject: (id: number, decidedBy: string, reason = '') =>
    post<{ ok: boolean }>(`/api/approvals/${id}/reject`, { decided_by: decidedBy, reason }),
  reset: () => post<{ ok: boolean; checking_balance: number }>('/api/reset', { confirm: 'RESET' }),
}
