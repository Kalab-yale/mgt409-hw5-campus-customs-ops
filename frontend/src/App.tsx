import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE, api } from './api'
import { APPROVAL_KINDS } from './agents'
import { ActivityFeed } from './components/ActivityFeed'
import { ApprovalsPanel } from './components/ApprovalsPanel'
import { CashCard } from './components/CashCard'
import { TeamPanel } from './components/TeamPanel'
import { TicketDetail } from './components/TicketDetail'
import { TicketList } from './components/TicketList'
import { money } from './format'
import type { Approval, Cash, Contributions, FeedItem, Run, Ticket } from './types'
import { usePolling } from './usePolling'

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [shopToday, setShopToday] = useState('')
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  // ?ticket=102 opens a specific ticket (handy for links and screenshots).
  const [selectedId, setSelectedId] = useState<number>(() => Number(new URLSearchParams(location.search).get('ticket')) || 101)
  const [feed, setFeed] = useState<{ ticketId: number; since: number; runId: string | null; items: FeedItem[] }>(
    { ticketId: 0, since: 0, runId: null, items: [] },
  )
  const [contrib, setContrib] = useState<Contributions | null>(null)
  const [runs, setRuns] = useState<Record<number, Run>>({}) // latest run per ticket
  const [approver, setApprover] = useState(() => localStorage.getItem('approver') || 'manager')
  const [lastCashChange, setLastCashChange] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  const runningRun = Object.values(runs).find(r => r.status === 'running') ?? null
  const anyRunning = !!runningRun || tickets.some(t => t.running)
  const selected = tickets.find(t => t.id === selectedId) ?? null
  const selectedRunning = !!selected?.running || runningRun?.ticket_id === selectedId
  const busyElsewhere = (runningRun && runningRun.ticket_id !== selectedId ? runningRun.ticket_id : null)
    ?? tickets.find(t => t.running && t.id !== selectedId)?.id ?? null

  useEffect(() => { localStorage.setItem('approver', approver) }, [approver])
  useEffect(() => {
    const url = new URL(location.href)
    url.searchParams.set('ticket', String(selectedId))
    history.replaceState(null, '', url)
  }, [selectedId])
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 5000); return () => clearTimeout(t) }, [toast])

  // --- shop state: tickets, cash, approvals (faster while the team is working)
  const refreshShop = useCallback(async () => {
    try {
      const [t, c, a] = await Promise.all([api.tickets(), api.cash(), api.approvals()])
      setTickets(t.tickets)
      setShopToday(t.shop_today)
      setCash(c)
      setApprovals(a.requests)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])
  usePolling(refreshShop, anyRunning ? 1500 : 4000)

  // Pick up runs already in progress (e.g. after a page reload).
  usePolling(async () => {
    const { runs: all } = await api.runs()
    const latest: Record<number, Run> = {}
    for (const r of all) latest[r.ticket_id] = r
    setRuns(latest)
  }, anyRunning ? 1500 : 8000)

  // --- selected ticket: activity feed (incremental) + per-agent contributions
  const feedRef = useRef(feed)
  feedRef.current = feed
  const selectedRef = useRef(selectedId)
  selectedRef.current = selectedId
  const feedBusy = useRef(false)

  const refreshFeed = useCallback(async () => {
    if (feedBusy.current) return // don't overlap polls (would double-append)
    feedBusy.current = true
    try {
      const prev = feedRef.current
      const cur = prev.ticketId === selectedId ? prev : { ticketId: selectedId, since: 0, runId: null, items: [] }
      let res = await api.feed(selectedId, cur.since)
      let items = [...cur.items, ...res.items]
      if (cur.since > 0 && res.run_id !== cur.runId) {
        // A different run appeared (new run started or database reset): load it from the start.
        res = await api.feed(selectedId, 0)
        items = res.items
      }
      if (selectedRef.current !== selectedId) return // user switched tickets mid-request
      setFeed({ ticketId: selectedId, since: res.last_seq, runId: res.run_id, items })
    } finally {
      feedBusy.current = false
    }
  }, [selectedId])
  usePolling(refreshFeed, selectedRunning ? 1200 : 4000, [selectedId])

  const refreshContrib = useCallback(async () => {
    setContrib(await api.contributions(selectedId))
  }, [selectedId])
  usePolling(refreshContrib, selectedRunning ? 1500 : 5000, [selectedId])

  useEffect(() => { setError(null) }, [selectedId])
  usePolling(() => setNow(Date.now()), selectedRunning ? 1000 : null)

  // --- actions
  const startRun = async () => {
    setError(null)
    try {
      const run = await api.run(selectedId)
      setRuns(r => ({ ...r, [run.ticket_id]: run }))
      setFeed({ ticketId: selectedId, since: 0, runId: null, items: [] })
      setTickets(ts => ts.map(t => (t.id === selectedId ? { ...t, running: true } : t)))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Poll the active run until it finishes, then refresh everything once.
  usePolling(async () => {
    if (!runningRun) return
    const r = await api.getRun(runningRun.run_id)
    if (r.status !== 'running') {
      setRuns(rs => ({ ...rs, [r.ticket_id]: r }))
      await Promise.all([refreshShop(), refreshContrib()])
      if (r.status === 'done') setToast(`Ticket ${r.ticket_id} ${r.resolved ? 'resolved ✓' : 'finished'}`)
      else setError(r.error ?? 'The run stopped early.')
    }
  }, runningRun ? 1500 : null, [runningRun?.run_id])

  const approve = async (a: Approval) => {
    try {
      const res = await api.approve(a.id, approver.trim() || 'manager')
      if (res.amount != null && res.old_balance != null && res.new_balance != null) {
        setLastCashChange(`${APPROVAL_KINDS[a.kind].label} approved by ${approver}: ${money(res.old_balance)} → ${money(res.new_balance)}`)
        setToast(`Paid ${money(res.amount)} · checking now ${money(res.new_balance)}`)
      } else {
        setToast(`${APPROVAL_KINDS[a.kind].label} #${a.id} approved`)
      }
    } catch (e) {
      setToast(`Couldn't approve: ${(e as Error).message}`)
    }
    await refreshShop()
  }

  const reject = async (a: Approval) => {
    try {
      await api.reject(a.id, approver.trim() || 'manager')
      setToast(`${APPROVAL_KINDS[a.kind].label} #${a.id} rejected. Nothing was paid or sent.`)
    } catch (e) {
      setToast(`Couldn't reject: ${(e as Error).message}`)
    }
    await refreshShop()
  }

  const reset = async () => {
    if (!window.confirm('Reset the shop database to its original values? Approvals, payments, and ticket statuses will be cleared. The audit trail is kept.')) return
    try {
      await api.reset()
      setRuns({})
      setFeed({ ticketId: selectedId, since: 0, runId: null, items: [] })
      setContrib(null)
      setLastCashChange(null)
      setToast('Database reset to original values')
      await Promise.all([refreshShop(), refreshContrib()])
    } catch (e) {
      setToast(`Couldn't reset: ${(e as Error).message}`)
    }
  }

  const decision = runs[selectedId]?.decision ?? contrib?.decision ?? null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">CC</span>
          <div>
            <div className="brand-name">Campus Customs</div>
            <div className="brand-sub">Ops Desk · Chapel Street</div>
          </div>
        </div>

        <div className="topbar-mid">
          <div className="desk-date" title="The shop's 'today' from the desk table">
            <span className="desk-date-label">Shop date</span>
            <span className="desk-date-value">{shopToday || '—'}</span>
          </div>
          <a href="#approvals" className={`approvals-chip ${approvals.length ? 'hot' : ''}`}>
            <span className="count">{approvals.length}</span> awaiting approval
          </a>
        </div>

        <CashCard cash={cash} lastChange={lastCashChange} />

        <div className="topbar-right">
          <label className="approver">
            <span>Approving as</span>
            <input value={approver} onChange={e => setApprover(e.target.value)} maxLength={60} />
          </label>
          <button className="btn btn-quiet small" onClick={reset} disabled={anyRunning} title="Restore the original database">
            ↺ Reset
          </button>
        </div>
      </header>

      {offline && (
        <div className="offline">Can't reach the backend at {API_BASE}. Start it from <code>backend/</code> with <code>uvicorn main:app --reload --port 8000</code>.</div>
      )}

      <main className="desk">
        <aside className="col col-left">
          <TicketList tickets={tickets} selectedId={selectedId} onSelect={setSelectedId} />
          <ApprovalsPanel
            approvals={approvals}
            balance={cash?.balance ?? null}
            selectedTicket={selectedId}
            onApprove={approve}
            onReject={reject}
          />
        </aside>

        <section className="col col-center">
          {selected ? (
            <TicketDetail
              ticket={selected}
              run={runs[selectedId] ?? null}
              decision={decision}
              busyElsewhere={busyElsewhere}
              error={error}
              onRun={startRun}
              now={now}
            />
          ) : (
            <section className="panel"><p className="empty">Loading tickets…</p></section>
          )}
          <ActivityFeed items={feed.ticketId === selectedId ? feed.items : []} running={selectedRunning} hasRun={!!contrib?.run_id || feed.items.length > 0} />
        </section>

        <aside className="col col-right">
          <TeamPanel contributions={contrib} running={selectedRunning} />
        </aside>
      </main>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}
