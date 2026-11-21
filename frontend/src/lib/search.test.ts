import { describe, expect, it } from 'vitest'
import {
  activeFilterCount,
  toApiQuery,
  toFacetQuery,
  toggled,
  validateCatalogSearch,
} from './search'

describe('validateCatalogSearch', () => {
  it('keeps valid values and accepts both JSON-parsed and string forms', () => {
    expect(
      validateCatalogSearch({
        q: '  polo  ',
        gender: 'women',
        brand: [3, '7', 3],
        size: ['M', ' L ', ''],
        price_max: '5000',
        discount_min: 50,
        my_sizes: 'true',
        flags: ['new', 'price_drop'],
        sort: 'price_asc',
        product: 42,
      }),
    ).toEqual({
      q: 'polo',
      gender: ['women'],
      brand: [3, 7],
      size: ['M', 'L'],
      price_max: 5000,
      discount_min: 50,
      my_sizes: true,
      flags: ['new', 'price_drop'],
      sort: 'price_asc',
      product: 42,
    })
  })

  it('drops invalid values instead of failing', () => {
    expect(
      validateCatalogSearch({
        gender: ['aliens'],
        brand: ['x', -1, 1.5],
        discount_min: 150,
        price_min: 'cheap',
        flags: ['hot'],
        sort: 'random',
        product: 0,
        my_sizes: 'yes',
        unknown: 'ignored',
      }),
    ).toEqual({})
  })

  it('keeps category slugs and drops old numeric ids', () => {
    expect(
      validateCatalogSearch({
        category: ['clothing', 'clothing.jackets', 12, 'Clothing', 'a.b.c'],
      }),
    ).toEqual({ category: ['clothing', 'clothing.jackets'] })
  })

  it('omits the default sort so URLs stay short', () => {
    expect(validateCatalogSearch({ sort: 'discount_desc' })).toEqual({})
  })
})

describe('query helpers', () => {
  const search = validateCatalogSearch({ brand: [1], sort: 'newest', product: 9, q: 'cap' })

  it('removes UI-only state from API queries', () => {
    expect(toApiQuery(search)).toEqual({ brand: [1], sort: 'newest', q: 'cap' })
    expect(toFacetQuery(search)).toEqual({ brand: [1], q: 'cap' })
  })

  it('counts active filters, not sort or the open item', () => {
    expect(activeFilterCount(search)).toBe(2)
    expect(activeFilterCount({})).toBe(0)
  })

  it('toggles list values and clears empty lists', () => {
    expect(toggled(undefined, 'M')).toEqual(['M'])
    expect(toggled(['M', 'L'], 'M')).toEqual(['L'])
    expect(toggled(['M'], 'M')).toBeUndefined()
  })
})
