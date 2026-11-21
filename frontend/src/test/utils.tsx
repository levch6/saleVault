import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { vi } from 'vitest'
import type { Facets, ProductCard, RunOut, SiteOut } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'

export function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  })
}

/** Renders with the providers the app has at its root; pass a client to pre-seed its cache. */
export function renderWithClient(ui: ReactElement, client: QueryClient = newClient()) {
  const user = userEvent.setup()
  const result = render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...result, client, user }
}

export interface ApiCall {
  method: string
  path: string
  body: unknown
}

type Route = unknown | ((call: ApiCall) => unknown)

/**
 * Stubs `fetch` with handlers keyed by `METHOD /path`. A handler is a JSON body, a function of the
 * call, or a function returning a `Response` (a `Response` can be read only once). Unknown routes
 * answer 404. Returns the list of calls, filled in as they happen.
 */
export function mockApi(routes: Record<string, Route>): ApiCall[] {
  const calls: ApiCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const text = await request.text()
      const call: ApiCall = {
        method: request.method,
        path: new URL(request.url).pathname,
        body: text ? JSON.parse(text) : undefined,
      }
      calls.push(call)
      const route = routes[`${call.method} ${call.path}`]
      if (route === undefined) return new Response('not found', { status: 404 })
      const result = typeof route === 'function' ? route(call) : route
      return result instanceof Response ? result : Response.json(result)
    }),
  )
  return calls
}

export const noContent = () => new Response(null, { status: 204 })

export function product(overrides: Partial<ProductCard> = {}): ProductCard {
  return {
    id: 7,
    site: 'prm',
    url: 'https://shop.example/p/7',
    brand: { id: 1, name: 'Acme' },
    name: 'Wool coat',
    subtitle: null,
    color: null,
    image: { thumb: 'https://img.example/7-thumb.jpg', full: 'https://img.example/7.jpg' },
    price: 1200,
    price_regular: 3000,
    price_min30: 3000,
    currency: 'UAH',
    discount_pct: 60,
    discount_min30_pct: 60,
    savings: 1800,
    prev_price: null,
    badges: [],
    genders: ['women'],
    sizes: [],
    is_favorite: false,
    is_active: true,
    first_seen_at: '2026-11-20T10:00:00Z',
    ...overrides,
  }
}

export function facets(overrides: Partial<Facets> = {}): Facets {
  return {
    total: 1234,
    sites: [{ value: 'prm', label: 'PRM', count: 1234 }],
    genders: [
      { value: 'men', label: 'Men', count: 700 },
      { value: 'women', label: 'Women', count: 534 },
      { value: 'home', label: 'Home', count: 0 },
      { value: 'kids', label: 'Kids', count: 0 },
    ],
    categories: [],
    brands: [
      { id: 'acme', name: 'Acme', count: 40 },
      { id: 'borealis', name: 'Borealis', count: 30 },
    ],
    sizes: null,
    price: { min: 100, max: 9000 },
    discount: { min: 10, max: 80 },
    ...overrides,
  }
}

export function run(overrides: Partial<RunOut> = {}): RunOut {
  return {
    id: 1,
    site: 'prm',
    status: 'success',
    trigger: 'cli',
    started_at: '2026-11-21T10:00:00Z',
    finished_at: '2026-11-21T10:08:00Z',
    expected_total: 100,
    pages_total: 10,
    pages_done: 10,
    items_seen: 100,
    stats: { seen: 100, new: 5, price_drops: 3, removed: 2 },
    error: null,
    ...overrides,
  }
}

export function site(overrides: Partial<SiteOut> = {}): SiteOut {
  const last = run({ site: overrides.code ?? 'prm' })
  return {
    code: 'prm',
    name: 'PRM',
    origin: 'https://shop.example',
    active_products: 100,
    last_completed: last,
    latest: last,
    resumable: false,
    ...overrides,
  }
}
