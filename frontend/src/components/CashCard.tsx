import { useEffect, useRef, useState } from 'react'
import { money } from '../format'
import type { Cash } from '../types'

/** Checking balance. When it drops, the number counts down and a red "−$X" chip appears. */
export function CashCard({ cash, lastChange }: { cash: Cash | null; lastChange: string | null }) {
  const target = cash?.balance ?? null
  const [shown, setShown] = useState<number | null>(target)
  const [delta, setDelta] = useState<number | null>(null)
  const prev = useRef<number | null>(target)

  useEffect(() => {
    if (target === null) return
    const from = prev.current
    prev.current = target
    if (from === null || from === target) {
      setShown(target)
      return
    }
    setDelta(target - from)
    const start = performance.now()
    const duration = 900
    let raf = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(from + (target - from) * eased)
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    const clear = window.setTimeout(() => setDelta(null), 6000)
    return () => { cancelAnimationFrame(raf); window.clearTimeout(clear) }
  }, [target])

  const pending = cash?.pending_money_out_total ?? 0
  const pct = cash && cash.balance > 0 ? Math.min(100, (pending / cash.balance) * 100) : 0
  const over = cash ? pending > cash.balance : false

  return (
    <section className="cash-card" aria-label="Checking balance">
      <div className="cash-top">
        <span className="eyebrow">Checking</span>
        {cash && <span className="cash-asof">as of {cash.as_of}</span>}
      </div>
      <div className="cash-amount-row">
        <span className={`cash-amount ${delta && delta < 0 ? 'dropping' : ''}`} aria-live="polite">
          {shown === null ? '—' : money(shown)}
        </span>
        {delta !== null && delta !== 0 && (
          <span className={`cash-delta ${delta < 0 ? 'down' : 'up'}`}>
            {delta < 0 ? '−' : '+'}
            {money(Math.abs(delta))}
          </span>
        )}
      </div>
      <div className="cash-bar" role="img" aria-label={`Pending payments ${money(pending)} of ${money(cash?.balance)}`}>
        <span className={`cash-bar-fill ${over ? 'over' : ''}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="cash-sub">
        {pending > 0 ? (
          <>
            <span>Pending payments <b>{money(pending)}</b></span>
            <span className={over ? 'neg' : ''}>After approval <b>{money(cash?.balance_if_pending_approved)}</b></span>
          </>
        ) : (
          <span>No payments waiting</span>
        )}
      </div>
      {lastChange && <div className="cash-last">{lastChange}</div>}
    </section>
  )
}
