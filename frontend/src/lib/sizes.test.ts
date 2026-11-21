import { describe, expect, it } from 'vitest'
import { compareSizes, groupSizes, sizeGroup } from './sizes'

describe('sizes', () => {
  it('recognizes size systems', () => {
    expect(sizeGroup('M')).toBe('letters')
    expect(sizeGroup('XS/S')).toBe('letters')
    expect(sizeGroup('42')).toBe('numbers')
    expect(sizeGroup('41 1/3')).toBe('numbers')
    expect(sizeGroup('W32 L34')).toBe('other')
  })

  it('orders letters by size and numbers by value', () => {
    expect(['XL', 'S', 'M', 'XXS', 'L/XL', 'XS/S'].sort(compareSizes)).toEqual([
      'XXS',
      'XS/S',
      'S',
      'M',
      'L/XL',
      'XL',
    ])
    expect(['42', '40 2/3', '41 1/3', '40'].sort(compareSizes)).toEqual([
      '40',
      '40 2/3',
      '41 1/3',
      '42',
    ])
  })

  it('groups and sorts facet entries', () => {
    const groups = groupSizes([{ label: '43' }, { label: 'L' }, { label: 'ONE' }, { label: 'S' }])

    expect(groups.letters.map((s) => s.label)).toEqual(['S', 'L'])
    expect(groups.numbers.map((s) => s.label)).toEqual(['43'])
    expect(groups.other.map((s) => s.label)).toEqual(['ONE'])
  })
})
