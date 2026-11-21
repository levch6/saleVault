import {
  type InfiniteData,
  infiniteQueryOptions,
  keepPreviousData,
  type QueryClient,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import type { ApiCatalogQuery } from '@/lib/search'
import { api } from './client'
import type { FavoriteOut, ProductCard, ProductDetail, ProductPage, SiteOut } from './types'

export const PAGE_SIZE = 60

/** Turn an openapi-fetch error body into an Error with the API's `detail` message. */
function apiError(error: unknown, response: Response): Error {
  const detail =
    error && typeof error === 'object' && 'detail' in error ? error.detail : response.statusText
  return new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`)
}

export const healthQuery = queryOptions({
  queryKey: ['health'],
  queryFn: async ({ signal }) => {
    const { data, response } = await api.GET('/api/health', { signal })
    if (!data) throw new Error(`API unavailable (HTTP ${response.status})`)
    return data
  },
  retry: false,
  refetchInterval: 10_000,
})

export const productsQuery = (query: ApiCatalogQuery) =>
  infiniteQueryOptions({
    queryKey: ['products', query],
    queryFn: async ({ pageParam, signal }) => {
      const { data, error, response } = await api.GET('/api/products', {
        params: { query: { ...query, page: pageParam, page_size: PAGE_SIZE } },
        signal,
      })
      if (!data) throw apiError(error, response)
      return data
    },
    initialPageParam: 1,
    getNextPageParam: (last: ProductPage) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    placeholderData: keepPreviousData,
  })

export const facetsQuery = (query: Omit<ApiCatalogQuery, 'sort'>, heavy = true) =>
  queryOptions({
    queryKey: ['facets', query, heavy],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET('/api/facets', {
        params: { query: { ...query, heavy } },
        signal,
      })
      if (!data) throw apiError(error, response)
      return data
    },
    placeholderData: keepPreviousData,
  })

export const productQuery = (id: number) =>
  queryOptions({
    queryKey: ['product', id],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET('/api/products/{product_id}', {
        params: { path: { product_id: id } },
        signal,
      })
      if (!data) throw apiError(error, response)
      return data
    },
  })

export const sitesQuery = queryOptions({
  queryKey: ['sites'],
  queryFn: async ({ signal }) => {
    const { data, error, response } = await api.GET('/api/sites', { signal })
    if (!data) throw apiError(error, response)
    return data
  },
  // Poll fast while a run is in progress (that is how the UI shows progress).
  refetchInterval: (query) =>
    query.state.data?.some((s) => s.latest?.status === 'running') ? 1500 : 30_000,
})

export const runsQuery = (limit = 50) =>
  queryOptions({
    queryKey: ['runs', limit],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET('/api/runs', {
        params: { query: { limit } },
        signal,
      })
      if (!data) throw apiError(error, response)
      return data
    },
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'running') ? 1500 : 30_000,
  })

export const settingsQuery = queryOptions({
  queryKey: ['settings'],
  queryFn: async ({ signal }) => {
    const { data, error, response } = await api.GET('/api/settings', { signal })
    if (!data) throw apiError(error, response)
    return data
  },
  staleTime: Number.POSITIVE_INFINITY,
})

export const favoritesQuery = queryOptions({
  queryKey: ['favorites'],
  queryFn: async ({ signal }) => {
    const { data, error, response } = await api.GET('/api/favorites', { signal })
    if (!data) throw apiError(error, response)
    return data
  },
})

/** Data changed (a run finished, settings changed): refetch everything derived from it. */
export function invalidateCatalog(client: QueryClient) {
  for (const key of ['products', 'facets', 'product', 'favorites', 'sites', 'runs']) {
    void client.invalidateQueries({ queryKey: [key] })
  }
}

function patchFavorite(client: QueryClient, id: number, isFavorite: boolean) {
  const patch = (card: ProductCard) =>
    card.id === id ? { ...card, is_favorite: isFavorite } : card
  client.setQueriesData<InfiniteData<ProductPage>>({ queryKey: ['products'] }, (data) =>
    data ? { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.map(patch) })) } : data,
  )
  client.setQueryData<ProductDetail>(['product', id], (d) =>
    d ? { ...d, is_favorite: isFavorite } : d,
  )
  client.setQueryData<FavoriteOut[]>(['favorites'], (list) =>
    list && !isFavorite ? list.filter((f) => f.product.id !== id) : list,
  )
}

export function useToggleFavorite() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, favorite }: { id: number; favorite: boolean }) => {
      const result = favorite
        ? await api.PUT('/api/favorites/{product_id}', { params: { path: { product_id: id } } })
        : await api.DELETE('/api/favorites/{product_id}', { params: { path: { product_id: id } } })
      if (!result.response.ok) throw apiError(result.error, result.response)
    },
    onMutate: ({ id, favorite }) => patchFavorite(client, id, favorite),
    onError: (_error, { id, favorite }) => patchFavorite(client, id, !favorite),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['favorites'] })
      void client.invalidateQueries({ queryKey: ['facets'] })
    },
  })
}

export function useUpdateMySizes() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (mySizes: string[]) => {
      const { data, error, response } = await api.PUT('/api/settings', {
        body: { my_sizes: mySizes },
      })
      if (!data) throw apiError(error, response)
      return data
    },
    onSuccess: (data) => {
      client.setQueryData(['settings'], data)
      void client.invalidateQueries({ queryKey: ['products'] })
      void client.invalidateQueries({ queryKey: ['product'] })
      void client.invalidateQueries({ queryKey: ['facets'] })
    },
  })
}

export function useStartRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ site, resume = false }: { site: string; resume?: boolean }) => {
      const { data, error, response } = await api.POST('/api/runs', { body: { site, resume } })
      if (!data) throw apiError(error, response)
      return data
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['sites'] })
      void client.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export function useCancelRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (runId: number) => {
      const { data, error, response } = await api.POST('/api/runs/{run_id}/cancel', {
        params: { path: { run_id: runId } },
      })
      if (!data) throw apiError(error, response)
      return data
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['sites'] })
      void client.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export function runningSites(sites: readonly SiteOut[] | undefined): SiteOut[] {
  return (sites ?? []).filter((s) => s.latest?.status === 'running')
}

/** Shop display name, and whether shops should be labeled at all (only with 2+ shops in data). */
export function useSiteLabel(code: string): { name: string; show: boolean } {
  const { data } = useQuery(sitesQuery)
  const withData = (data ?? []).filter((s) => s.active_products > 0)
  return {
    name: data?.find((s) => s.code === code)?.name ?? code,
    show: withData.length > 1,
  }
}
