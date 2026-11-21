import { describe, expect, it } from 'vitest'
import { formatPrice } from './format'

// Intl uses no-break spaces as group separators; normalize them for readable assertions.
const plain = (s: string) => s.replace(/\s/g, ' ')

describe('formatPrice', () => {
  it('formats whole hryvnias with grouping and the hryvnia sign', () => {
    expect(plain(formatPrice(17899))).toBe('17 899 ₴')
  })

  it('drops fractional kopecks', () => {
    expect(plain(formatPrice(269.4))).toBe('269 ₴')
  })
})
