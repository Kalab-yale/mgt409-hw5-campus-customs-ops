import { useEffect, useRef } from 'react'
import { agentStyle } from '../agents'
import { clock, formatArgs, prettyJson } from '../format'
import type { FeedItem } from '../types'
import { AgentAvatar, AgentChip } from './AgentBadge'

const KIND_LABEL: Record<FeedItem['kind'], string> = {
  said: 'Message',
  report: 'Report',
  tool: 'Tool',
  delegation: 'Hand-off',
  guardrail: 'Guardrail',
  run_started: 'Started',
  decision: 'Decision',
  error: 'Error',
  human_approved: 'Approved',
  human_rejected: 'Rejected',
  ticket_resolved: 'Resolved',
  database_reset: 'Reset',
}

function Item({ item }: { item: FeedItem }) {
  const s = agentStyle(item.agent)
  return (
    <li className={`feed-item k-${item.kind}`} style={{ ['--agent' as string]: s.color, ['--agent-soft' as string]: s.soft }}>
      <AgentAvatar agent={item.agent} size={30} />
      <div className="feed-body">
        <div className="feed-meta">
          <span className="feed-agent" style={{ color: s.color }}>{s.name}</span>
          <span className="feed-kind">{KIND_LABEL[item.kind] ?? item.kind}</span>
          <time className="feed-time">{clock(item.ts)}</time>
        </div>

        {item.kind === 'tool' ? (
          <details className="tool-call">
            <summary>
              <code className="tool-name">{item.tool}</code>
              <code className="tool-args">({formatArgs(item.args)})</code>
            </summary>
            <pre className="tool-result">{prettyJson(item.result_preview)}</pre>
          </details>
        ) : item.kind === 'delegation' ? (
          <>
            <div className="handoff">
              <AgentChip agent={item.agent} /> <span className="arrow" aria-label="delegates to">→</span> <AgentChip agent={item.to_agent} />
            </div>
            <p className="feed-text">{item.text}</p>
          </>
        ) : (
          <p className="feed-text">{item.text}</p>
        )}
        {item.kind === 'decision' && item.usage?.total_tokens != null && (
          <div className="small muted">{item.usage.total_tokens.toLocaleString()} tokens · {item.usage.requests} model calls · {item.usage.tool_calls} tool calls</div>
        )}
      </div>
    </li>
  )
}

export function ActivityFeed({ items, running, hasRun }: { items: FeedItem[]; running: boolean; hasRun: boolean }) {
  const listRef = useRef<HTMLOListElement>(null)
  const stick = useRef(true)

  useEffect(() => {
    const el = listRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [items.length])

  const tools = items.filter(i => i.kind === 'tool').length
  const handoffs = items.filter(i => i.kind === 'delegation').length

  return (
    <section className="panel feed-panel" aria-labelledby="feed-title">
      <div className="panel-head">
        <h2 id="feed-title">Live activity {running && <span className="live-dot" aria-label="live" />}</h2>
        {hasRun && <span className="muted small">{handoffs} hand-offs · {tools} tool calls</span>}
      </div>
      {!hasRun ? (
        <p className="empty">No run yet. Start the team and every message, hand-off, and MCP tool call appears here as it happens.</p>
      ) : (
        <ol
          className="feed"
          ref={listRef}
          onScroll={e => {
            const el = e.currentTarget
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
          }}
          aria-live="polite"
        >
          {items.map((it, i) => <Item key={`${it.seq}-${i}`} item={it} />)}
          {running && <li className="feed-waiting"><span className="spinner" aria-hidden="true" /> waiting for the next step…</li>}
        </ol>
      )}
    </section>
  )
}
