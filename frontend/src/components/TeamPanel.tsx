import { useState } from 'react'
import { AGENTS, AGENT_ORDER, agentStyle } from '../agents'
import type { AgentContribution, AgentName, Contributions } from '../types'
import { AgentAvatar } from './AgentBadge'

function AgentCard({ name, c, hasRun, running }: {
  name: AgentName
  c: AgentContribution | undefined
  hasRun: boolean
  running: boolean
}) {
  const s = AGENTS[name]
  const [open, setOpen] = useState(false)
  const status = c ? c.status : hasRun && !running ? 'skipped' : 'idle'
  const label = { working: 'Working', done: 'Done', error: 'Stopped', skipped: 'Not needed', idle: 'Idle' }[status]
  const tools = c ? Object.entries(c.tools) : []

  return (
    <li className={`agent-card st-${status}`} style={{ ['--agent' as string]: s.color, ['--agent-soft' as string]: s.soft }}>
      <div className="agent-head">
        <AgentAvatar agent={name} size={38} />
        <div className="agent-id">
          <div className="agent-name" style={{ color: s.color }}>{s.name}</div>
          <div className="agent-role">{s.role}</div>
        </div>
        <span className={`agent-status st-${status}`}>
          {status === 'working' && <span className="pulse" />}
          {label}
        </span>
      </div>

      {c && (
        <div className="agent-contrib">
          {c.summary ? (
            <p className={`agent-summary ${open ? 'open' : ''}`} onClick={() => setOpen(o => !o)} title="Click to expand">
              {c.summary}
            </p>
          ) : (
            <p className="agent-summary muted">Working on it…</p>
          )}
          {(c.delegated_by.length > 0 || c.delegated_to.length > 0) && (
            <div className="agent-links small">
              {c.delegated_by.length > 0 && <span>Asked by {c.delegated_by.map(a => agentStyle(a).name).join(', ')}</span>}
              {c.delegated_to.length > 0 && <span>Delegated to {c.delegated_to.map(a => agentStyle(a).name).join(', ')}</span>}
            </div>
          )}
          {tools.length > 0 && (
            <div className="agent-tools">
              {tools.map(([t, n]) => <code key={t} className="tool-chip">{t}{n > 1 ? ` ×${n}` : ''}</code>)}
            </div>
          )}
          {c.approval_request_ids.length > 0 && (
            <div className="small agent-requests">Requests: {c.approval_request_ids.map(id => `#${id}`).join(', ')}</div>
          )}
        </div>
      )}
    </li>
  )
}

export function TeamPanel({ contributions, running }: { contributions: Contributions | null; running: boolean }) {
  const hasRun = !!contributions?.run_id
  const involved = hasRun ? Object.keys(contributions!.agents).length : 0
  return (
    <section className="panel" aria-labelledby="team-title">
      <div className="panel-head">
        <h2 id="team-title">The team</h2>
        <span className="muted small">{hasRun ? `${involved} of 5 on this ticket` : '5 agents'}</span>
      </div>
      <ul className="agent-list">
        {AGENT_ORDER.map(name => (
          <AgentCard key={name} name={name} c={contributions?.agents[name]} hasRun={hasRun} running={running} />
        ))}
      </ul>
    </section>
  )
}
