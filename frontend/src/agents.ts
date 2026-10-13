// One identity per agent: color + icon + name, so agents never rely on color alone.
import type { ActorName, AgentName, ApprovalKind } from './types'

export interface AgentStyle {
  name: string
  role: string
  icon: string
  color: string // text/accents (WCAG AA on white)
  soft: string // tinted backgrounds
}

export const AGENT_ORDER: AgentName[] = ['boss', 'inventory', 'accounting', 'facilities', 'customer_service']

export const AGENTS: Record<ActorName, AgentStyle> = {
  boss: { name: 'Boss', role: 'Reviews tickets, assigns work, makes the call', icon: '👔', color: '#5146D9', soft: '#EEEDFC' },
  inventory: { name: 'Inventory', role: 'Stock by SKU & size, shortages, restock vendors', icon: '📦', color: '#B45309', soft: '#FDF1E3' },
  accounting: { name: 'Accounting', role: 'Cash, invoices, margins; prepares payments', icon: '🧮', color: '#1E7A3C', soft: '#E6F4EA' },
  facilities: { name: 'Facilities', role: 'Shop space, lease, and rent', icon: '🏬', color: '#0062C4', soft: '#E5EFFA' },
  customer_service: { name: 'Customer Service', role: 'Drafts honest customer messages', icon: '💬', color: '#B8195A', soft: '#FBE7EF' },
  human: { name: 'You', role: 'Manager', icon: '👤', color: '#1D1D1F', soft: '#ECECEE' },
}

export const agentStyle = (name: string | null | undefined): AgentStyle =>
  AGENTS[(name ?? 'human') as ActorName] ?? AGENTS.human

export const TICKET_TYPES: Record<string, { label: string; icon: string }> = {
  customer_order: { label: 'Customer order', icon: '🛍️' },
  rent_notice: { label: 'Rent notice', icon: '🏠' },
  price_override: { label: 'Discount request', icon: '🏷️' },
}

export const APPROVAL_KINDS: Record<ApprovalKind, { label: string; icon: string; moneyOut: boolean }> = {
  invoice_payment: { label: 'Invoice payment', icon: '🧾', moneyOut: true },
  rent_payment: { label: 'Rent payment', icon: '🏠', moneyOut: true },
  purchase_order: { label: 'Purchase order', icon: '📦', moneyOut: true },
  price_quote: { label: 'Price quote', icon: '🏷️', moneyOut: false },
  customer_message: { label: 'Customer message', icon: '✉️', moneyOut: false },
}
