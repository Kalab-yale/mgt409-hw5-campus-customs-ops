import { TICKET_TYPES } from '../agents'
import { elapsed } from '../format'
import type { Run, Ticket, TicketDecision } from '../types'
import { AgentChip } from './AgentBadge'
import { StatusPill } from './TicketList'

const DECISION_LABEL: Record<TicketDecision['decision'], string> = {
  awaiting_approval: 'Awaiting your approval',
  blocked: 'Blocked',
  in_progress: 'In progress',
  no_action_needed: 'No action needed',
}

export function TicketDetail({ ticket, run, decision, busyElsewhere, error, onRun, now }: {
  ticket: Ticket
  run: Run | null
  decision: TicketDecision | null
  busyElsewhere: number | null
  error: string | null
  onRun: () => void
  now: number
}) {
  const type = TICKET_TYPES[ticket.type] ?? { label: ticket.type, icon: '📄' }
  const running = ticket.running || run?.status === 'running'
  const resolved = ticket.status === 'resolved'

  const facts: [string, string][] = []
  if (ticket.sku) facts.push(['Item', `${ticket.qty ?? ''} × ${ticket.sku}${ticket.size ? ` · size ${ticket.size}` : ''}`])
  if (ticket.lease_id) facts.push(['Lease', `#${ticket.lease_id}`])
  if (ticket.invoice_id) facts.push(['Linked invoice', `#${ticket.invoice_id}`])
  facts.push(['Received', new Date(ticket.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })])

  return (
    <section className="panel detail" aria-labelledby="detail-title">
      <div className="detail-head">
        <div>
          <div className="detail-eyebrow">
            <span aria-hidden="true">{type.icon}</span> {type.label} · #{ticket.id}
          </div>
          <h2 id="detail-title" className="detail-title">{ticket.subject}</h2>
          <div className="detail-from">from <b>{ticket.requester}</b></div>
        </div>
        <StatusPill ticket={{ ...ticket, running }} />
      </div>

      {ticket.notes && <p className="detail-notes">“{ticket.notes}”</p>}
      <dl className="detail-facts">
        {facts.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>

      {resolved ? (
        <div className="resolved-banner" role="status">
          <span className="resolved-check" aria-hidden="true">✓</span>
          <div>
            <b>Resolved.</b> The team finished this ticket.
            {ticket.pending_approvals > 0
              ? <> <a href="#approvals">{ticket.pending_approvals} request{ticket.pending_approvals > 1 ? 's' : ''} waiting for your approval →</a></>
              : ' Nothing left to approve.'}
          </div>
        </div>
      ) : (
        <div className="run-row">
          <button className="btn btn-run" onClick={onRun} disabled={running || busyElsewhere !== null}>
            {running ? <><span className="spinner" aria-hidden="true" /> Team working…</> : '▶ Run agent team'}
          </button>
          <span className="muted small" aria-live="polite">
            {running && run ? `Elapsed ${elapsed(run.started_at, new Date(now).toISOString())} · the Boss is delegating to specialists`
              : busyElsewhere !== null ? `The team is busy on ticket ${busyElsewhere}.`
              : 'The Boss reads the ticket and pulls in only the specialists it needs.'}
          </span>
        </div>
      )}
      {error && <p className="error-line">{error}</p>}

      {decision && (
        <div className="decision-card">
          <div className="decision-head">
            <AgentChip agent="boss" />
            <span className="small muted">Final decision</span>
            <span className={`decision-tag d-${decision.decision}`}>{DECISION_LABEL[decision.decision]}</span>
          </div>
          <p className="decision-summary">{decision.summary}</p>
          {decision.plan.length > 0 && (
            <>
              <h3 className="mini-title">Next steps</h3>
              <ol className="decision-plan">{decision.plan.map((p, i) => <li key={i}>{p}</li>)}</ol>
            </>
          )}
          {decision.risks.length > 0 && (
            <>
              <h3 className="mini-title">Watch out</h3>
              <ul className="decision-risks">{decision.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}
          {run?.finished_at && <div className="small muted">Finished in {elapsed(run.started_at, run.finished_at)}</div>}
        </div>
      )}
    </section>
  )
}
