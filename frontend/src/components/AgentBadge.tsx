import { agentStyle } from '../agents'

/** Colored icon tile + name. Icon and label carry identity, so it works without color too. */
export function AgentAvatar({ agent, size = 32 }: { agent: string | null | undefined; size?: number }) {
  const s = agentStyle(agent)
  return (
    <span
      className="avatar"
      style={{ width: size, height: size, background: s.soft, borderColor: s.color, fontSize: size * 0.5 }}
      title={s.name}
      aria-hidden="true"
    >
      {s.icon}
    </span>
  )
}

export function AgentChip({ agent }: { agent: string | null | undefined }) {
  const s = agentStyle(agent)
  return (
    <span className="agent-chip" style={{ color: s.color, background: s.soft }}>
      <span aria-hidden="true">{s.icon}</span> {s.name}
    </span>
  )
}
