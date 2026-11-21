const uah = new Intl.NumberFormat('uk-UA', {
  style: 'currency',
  currency: 'UAH',
  maximumFractionDigits: 0,
})

/** Format whole hryvnias the way the shops do, e.g. 17899 -> "17 899" + hryvnia sign. */
export function formatPrice(value: number): string {
  return uah.format(value)
}
