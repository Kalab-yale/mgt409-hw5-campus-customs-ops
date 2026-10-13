// Shapes returned by the FastAPI backend (backend/main.py).

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
export type ActorName = AgentName | 'human'

export interface Ticket {
  id: number
  type: 'customer_order' | 'rent_notice' | 'price_override' | string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: 'open' | 'resolved'
  stage: string
  notes: string | null
  created_at: string
  pending_approvals: number
  total_approvals: number
  running: boolean
}

export interface TicketsResponse {
  shop_today: string
  count: number
  tickets: Ticket[]
}

export interface PendingMoneyOut {
  id: number
  ticket_id: number
  kind: string
  ref_id: number | null
  amount: number
  summary: string
}

export interface Cash {
  account: string
  balance: number
  as_of: string
  shop_today: string
  pending_money_out_total: number
  balance_if_pending_approved: number
  pending_money_out_requests: PendingMoneyOut[]
}

export type ApprovalKind = 'invoice_payment' | 'rent_payment' | 'purchase_order' | 'price_quote' | 'customer_message'

export interface Approval {
  id: number
  ticket_id: number
  kind: ApprovalKind
  ref_id: number | null
  sku: string | null
  size: string | null
  qty: number | null
  unit_price: number | null
  amount: number | null
  summary: string
  message: string | null
  requested_by: AgentName
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
}

export interface TicketDecision {
  ticket_id: number
  decision: 'awaiting_approval' | 'blocked' | 'in_progress' | 'no_action_needed'
  summary: string
  plan: string[]
  approval_request_ids: number[]
  agents_consulted: AgentName[]
  risks: string[]
}

export interface Run {
  run_id: string
  ticket_id: number
  status: 'running' | 'done' | 'stopped' | 'error'
  started_at: string
  finished_at: string | null
  decision: TicketDecision | null
  error: string | null
  resolved: boolean
}

export type FeedKind =
  | 'said' | 'report' | 'tool' | 'delegation' | 'guardrail' | 'run_started' | 'decision' | 'error'
  | 'human_approved' | 'human_rejected' | 'ticket_resolved' | 'database_reset'

export interface FeedItem {
  seq: number
  ts: string
  run_id: string | null
  ticket_id: number | null
  agent: ActorName | null
  kind: FeedKind
  text: string
  tool?: string
  args?: Record<string, unknown>
  result_preview?: string
  to_agent?: AgentName
  decision?: TicketDecision
  usage?: { total_tokens?: number; requests?: number; tool_calls?: number }
}

export interface FeedResponse {
  items: FeedItem[]
  last_seq: number
  run_id: string | null
}

export interface AgentContribution {
  agent: AgentName
  status: 'working' | 'done' | 'error'
  summary: string
  facts: string[]
  tools: Record<string, number>
  delegated_to: AgentName[]
  delegated_by: AgentName[]
  approval_request_ids: number[]
  blockers: string[]
  needs_human: boolean
  invocations: number
}

export interface Contributions {
  ticket_id: number
  run_id: string | null
  finished: boolean
  decision?: TicketDecision | null
  agents: Partial<Record<AgentName, AgentContribution>>
}

export interface ApproveResult {
  ok: boolean
  request_id: number
  kind: ApprovalKind
  ticket_id: number
  amount?: number
  old_balance?: number
  new_balance?: number
  note?: string
}
