import { useState } from 'react'
import { APPROVAL_KINDS } from '../agents'
import { money } from '../format'
import type { Approval } from '../types'
import { AgentChip } from './AgentBadge'

export function ApprovalsPanel({ approvals, balance, selectedTicket, onApprove, onReject }: {
  approvals: Approval[]
  balance: number | null
  selectedTicket: number
  onApprove: (a: Approval) => Promise<void>
  onReject: (a: Approval) => Promise<void>
}) {
  const [busy, setBusy] = useState<number | null>(null)
  // The selected ticket's requests first, then the rest by id.
  const sorted = [...approvals].sort(
    (a, b) => Number(b.ticket_id === selectedTicket) - Number(a.ticket_id === selectedTicket) || a.id - b.id,
  )

  const act = async (a: Approval, fn: (a: Approval) => Promise<void>) => {
    setBusy(a.id)
    try { await fn(a) } finally { setBusy(null) }
  }

  return (
    <section className="panel" id="approvals" aria-labelledby="approvals-title">
      <div className="panel-head">
        <h2 id="approvals-title">Needs your approval</h2>
        <span className={`count-badge ${approvals.length ? 'hot' : ''}`}>{approvals.length}</span>
      </div>
      {approvals.length === 0 ? (
        <p className="empty">Nothing waiting. Agents prepare payments, orders, quotes, and messages here; nothing happens until you approve.</p>
      ) : (
        <ul className="approval-list">
          {sorted.map(a => {
            const k = APPROVAL_KINDS[a.kind]
            const short = k.moneyOut && balance !== null && (a.amount ?? 0) > balance
            return (
              <li key={a.id} className={`approval ${a.ticket_id === selectedTicket ? 'for-selected' : ''}`}>
                <div className="approval-top">
                  <span className="approval-kind"><span aria-hidden="true">{k.icon}</span> {k.label}</span>
                  <span className="muted small">#{a.id} · ticket {a.ticket_id}</span>
                </div>
                {a.amount != null && (
                  <div className={`approval-amount ${k.moneyOut ? 'out' : 'in'}`}>
                    {k.moneyOut ? '−' : ''}{money(a.amount)}
                    {a.kind === 'price_quote' && a.unit_price != null && a.qty != null && (
                      <span className="muted small"> · {a.qty} × {money(a.unit_price)}</span>
                    )}
                    {a.kind === 'purchase_order' && a.qty != null && (
                      <span className="muted small"> · {a.qty} × {a.sku} {a.size}</span>
                    )}
                  </div>
                )}
                <p className="approval-summary">{a.summary}</p>
                {a.message && <blockquote className="approval-message">{a.message}</blockquote>}
                <div className="approval-foot">
                  <span className="small muted">Prepared by</span> <AgentChip agent={a.requested_by} />
                </div>
                {short && <p className="warn small">Not enough cash in checking to pay this right now.</p>}
                <div className="approval-actions">
                  <button className="btn btn-primary" disabled={busy !== null || short} onClick={() => act(a, onApprove)}>
                    {busy === a.id ? 'Working…' : k.moneyOut ? `Approve & pay ${money(a.amount)}` : 'Approve'}
                  </button>
                  <button className="btn btn-quiet" disabled={busy !== null} onClick={() => act(a, onReject)}>
                    Reject
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
