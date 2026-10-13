import { useEffect, useRef } from 'react'

/** Call `fn` now and then every `ms` (pass null to pause). Always uses the latest `fn`. */
export function usePolling(fn: () => void | Promise<void>, ms: number | null, deps: unknown[] = []) {
  const saved = useRef(fn)
  saved.current = fn

  useEffect(() => {
    if (ms === null) return
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      try { await saved.current() } catch { /* surfaced by caller */ }
    }
    tick()
    const id = window.setInterval(tick, ms)
    return () => { cancelled = true; window.clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps])
}
