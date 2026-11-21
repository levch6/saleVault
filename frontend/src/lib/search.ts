import type { components, operations } from '@/api/schema'

/** Catalog state that lives in the URL (filters, sort, the open item). */

export type Gender = components['schemas']['ProductCard']['genders'][number]
export type Flag = 'new' | 'price_drop' | 'favorite'
export type ApiCatalogQuery = NonNullable<operations['list_products']['parameters']['query']>
export type Sort = NonNullable<ApiCatalogQuery['sort']>

export const GENDERS: readonly Gender[] = ['women', 'men', 'home', 'kids']
export const FLAGS: readonly Flag[] = ['new', 'price_drop', 'favorite']
export const SORTS: readonly { value: Sort; label: string }[] = [
  { value: 'discount_desc', label: 'Biggest discount' },
  { value: 'discount_min30_desc', label: 'Honest discount' },
  { value: 'savings_desc', label: 'Biggest savings' },
  { value: 'price_asc', label: 'Price: low to high' },
  { value: 'price_desc', label: 'Price: high to low' },
  { value: 'newest', label: 'Newest' },
]
const SORT_VALUES = SORTS.map((s) => s.value)
export const DEFAULT_SORT: Sort = 'discount_desc'

export interface CatalogSearch {
  q?: string
  site?: string[]
  gender?: Gender[]
  /** Shared category tree: a group (`clothing`) or a leaf (`clothing.jackets`). */
  category?: string[]
  brand?: number[]
  size?: string[]
  my_sizes?: boolean
  price_min?: number
  price_max?: number
  discount_min?: number
  discount_max?: number
  flags?: Flag[]
  sort?: Sort
  /** Id of the item open in the drawer. */
  product?: number
}

const asList = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : value === undefined ? [] : [value]

function strings(value: unknown, maxLength = 64): string[] | undefined {
  const out = asList(value)
    .filter((v): v is string | number => typeof v === 'string' || typeof v === 'number')
    .map((v) => String(v).trim())
    .filter((v) => v !== '' && v.length <= maxLength)
  return out.length ? [...new Set(out)] : undefined
}

function int(value: unknown, min: number, max: number): number | undefined {
  const n =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim() !== ''
        ? Number(value)
        : Number.NaN
  return Number.isInteger(n) && n >= min && n <= max ? n : undefined
}

function ints(value: unknown): number[] | undefined {
  const out = asList(value)
    .map((v) => int(v, 1, Number.MAX_SAFE_INTEGER))
    .filter((v): v is number => v !== undefined)
  return out.length ? [...new Set(out)] : undefined
}

const SLUG = /^[a-z]+(\.[a-z]+)?$/

/** Category slugs; old numeric ids from saved links are dropped. */
function slugs(value: unknown): string[] | undefined {
  const out = strings(value)?.filter((v) => SLUG.test(v))
  return out?.length ? out : undefined
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return allowed.find((a) => a === value)
}

function manyOf<T extends string>(value: unknown, allowed: readonly T[]): T[] | undefined {
  const out = asList(value)
    .map((v) => oneOf(v, allowed))
    .filter((v): v is T => v !== undefined)
  return out.length ? [...new Set(out)] : undefined
}

/** Turn whatever is in the URL into a valid search; invalid parts are dropped, not errors. */
export function validateCatalogSearch(raw: Record<string, unknown>): CatalogSearch {
  const q = typeof raw.q === 'string' || typeof raw.q === 'number' ? String(raw.q).trim() : ''
  const sort = oneOf(raw.sort, SORT_VALUES)
  const search: CatalogSearch = {
    q: q ? q.slice(0, 100) : undefined,
    site: strings(raw.site),
    gender: manyOf(raw.gender, GENDERS),
    category: slugs(raw.category),
    brand: ints(raw.brand),
    size: strings(raw.size),
    my_sizes: raw.my_sizes === true || raw.my_sizes === 'true' ? true : undefined,
    price_min: int(raw.price_min, 0, 10_000_000),
    price_max: int(raw.price_max, 0, 10_000_000),
    discount_min: int(raw.discount_min, 0, 100),
    discount_max: int(raw.discount_max, 0, 100),
    flags: manyOf(raw.flags, FLAGS),
    sort: sort === DEFAULT_SORT ? undefined : sort,
    product: int(raw.product, 1, Number.MAX_SAFE_INTEGER),
  }
  return compact(search)
}

/** Drop undefined keys so URLs stay short and equal searches compare equal. */
export function compact<T extends object>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T
}

/** Filters for the API (everything except UI-only state such as the open item). */
export function toApiQuery(search: CatalogSearch): ApiCatalogQuery {
  const { product: _product, ...filters } = search
  return compact(filters)
}

/** Filters only, without sort: what the facets endpoint takes. */
export function toFacetQuery(search: CatalogSearch) {
  const { sort: _sort, ...filters } = toApiQuery(search)
  return filters
}

export function activeFilterCount(search: CatalogSearch): number {
  const { sort: _sort, product: _product, ...filters } = search
  return Object.values(filters).filter((v) => v !== undefined).length
}

/** Add or remove a value; an empty list becomes undefined (removed from the URL). */
export function toggled<T>(list: readonly T[] | undefined, value: T): T[] | undefined {
  const next = list?.includes(value) ? list.filter((v) => v !== value) : [...(list ?? []), value]
  return next.length ? next : undefined
}
