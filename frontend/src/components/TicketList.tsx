import { TICKET_TYPES } from '../agents'
import type { Ticket } from '../types'

export function StatusPill({ ticket }: { ticket: Ticket }) {
  if (ticket.running) return <span className="pill pill-running"><span className="pulse" />Running</span>
  if (ticket.status === 'resolved') return <span className="pill pill-resolved">✓ Resolved</span>
  return <span className="pill pill-open">Open</span>
}

export function TicketList({ tickets, selectedId, onSelect }: {
  tickets: Ticket[]
  selectedId: number
  onSelect: (id: number) => void
}) {
  const resolved = tickets.filter(t => t.status === 'resolved').length
  return (
    <section className="panel" aria-labelledby="queue-title">
      <div className="panel-head">
        <h2 id="queue-title">Ticket queue</h2>
        <span className="muted small">{resolved}/{tickets.length} resolved</span>
      </div>
      <ul className="ticket-list">
        {tickets.map(t => {
          const type = TICKET_TYPES[t.type] ?? { label: t.type, icon: '📄' }
          return (
            <li key={t.id}>
              <button
                className={`ticket-stub ${t.id === selectedId ? 'selected' : ''} ${t.status === 'resolved' ? 'is-resolved' : ''}`}
                onClick={() => onSelect(t.id)}
                aria-pressed={t.id === selectedId}
              >
                <div className="stub-top">
                  <span className="stub-id">#{t.id}</span>
                  <StatusPill ticket={t} />
                </div>
                <div className="stub-subject">
                  <span aria-hidden="true">{type.icon}</span> {t.subject}
                </div>
                <div className="stub-meta">
                  <span>{t.requester}</span>
                  <span>{type.label}</span>
                </div>
                {t.pending_approvals > 0 && (
                  <div className="stub-approvals">⏳ {t.pending_approvals} waiting for approval</div>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
