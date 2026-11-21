/** Size labels come in many systems; group and order them the way people scan them. */

const LETTER_ORDER = ['XXXS', 'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '3XL', '4XL']

export type SizeGroup = 'letters' | 'numbers' | 'other'

export function sizeGroup(label: string): SizeGroup {
  const upper = label.toUpperCase()
  if (
    LETTER_ORDER.includes(upper) ||
    /^(X{0,3}[SML]|X{1,3}L)(\/(X{0,3}[SML]|X{1,3}L))?$/.test(upper)
  )
    return 'letters'
  if (/^\d+([.,]\d+)?( \d\/\d)?$/.test(label) || /^\d+\/\d+$/.test(label)) return 'numbers'
  return 'other'
}

/** "M" -> rank of M; a range like "XS/S" sorts right after its first size. */
function letterRank(label: string): number {
  const [first = '', second] = label.toUpperCase().split('/')
  const rank = LETTER_ORDER.indexOf(first)
  return (rank === -1 ? LETTER_ORDER.length : rank) + (second ? 0.5 : 0)
}

function numericValue(label: string): number {
  const [whole = '0', fraction] = label.replace(',', '.').split(' ')
  const base = Number.parseFloat(whole)
  if (!fraction) return base
  const [num = '0', den = '1'] = fraction.split('/')
  return base + Number(num) / Number(den)
}

export function compareSizes(a: string, b: string): number {
  const ga = sizeGroup(a)
  const gb = sizeGroup(b)
  if (ga !== gb) return ga.localeCompare(gb)
  if (ga === 'letters') return letterRank(a) - letterRank(b) || a.localeCompare(b)
  if (ga === 'numbers') return numericValue(a) - numericValue(b)
  return a.localeCompare(b)
}

export function groupSizes<T extends { label: string }>(
  items: readonly T[],
): Record<SizeGroup, T[]> {
  const groups: Record<SizeGroup, T[]> = { letters: [], numbers: [], other: [] }
  for (const item of [...items].sort((a, b) => compareSizes(a.label, b.label))) {
    groups[sizeGroup(item.label)].push(item)
  }
  return groups
}
