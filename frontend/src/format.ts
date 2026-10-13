const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export const money = (n: number | null | undefined) => (n == null ? '—' : usd.format(n))

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })

export const elapsed = (fromIso: string, toIso?: string | null) => {
  const secs = Math.max(0, Math.round(((toIso ? Date.parse(toIso) : Date.now()) - Date.parse(fromIso)) / 1000))
  return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
}

/** `{ sku: "CC-TEE-WHITE", size: "S" }` -> `sku="CC-TEE-WHITE", size="S"` (backend-stamped ids hidden). */
export const formatArgs = (args?: Record<string, unknown>) =>
  Object.entries(args ?? {})
    .filter(([k, v]) => v !== null && v !== undefined && k !== 'requested_by' && k !== 'updated_by')
    .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v.length > 40 ? v.slice(0, 40) + '…' : v}"` : JSON.stringify(v)}`)
    .join(', ')

export const prettyJson = (text?: string) => {
  if (!text) return ''
  try {
    return JSON.stringify(JSON.parse(text.replace(/…$/, '')), null, 2)
  } catch {
    return text
  }
}
