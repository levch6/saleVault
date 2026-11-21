const uah = new Intl.NumberFormat('uk-UA', {
  style: 'currency',
  currency: 'UAH',
  maximumFractionDigits: 0,
})
const count = new Intl.NumberFormat('en-US')
const dateTime = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})
const date = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

/** Format whole hryvnias the way the shops do, e.g. 17899 -> "17 899" + hryvnia sign. */
export function formatPrice(value: number): string {
  return uah.format(value)
}

export function formatCount(value: number): string {
  return count.format(value)
}

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

export function formatDate(iso: string): string {
  return date.format(new Date(iso))
}

export function formatDuration(fromIso: string, toIso: string | null | undefined): string {
  if (!toIso) return '-'
  const seconds = Math.max(0, (Date.parse(toIso) - Date.parse(fromIso)) / 1000)
  return seconds < 90 ? `${Math.round(seconds)} s` : `${(seconds / 60).toFixed(1)} min`
}

/** Color of a discount badge: the deeper the discount, the hotter the color. */
export function discountTone(pct: number): string {
  if (pct >= 70) return 'bg-red-800 text-white'
  if (pct >= 50) return 'bg-red-600 text-white'
  if (pct >= 30) return 'bg-orange-500 text-white'
  return 'bg-zinc-600 text-white'
}
