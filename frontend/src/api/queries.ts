import { queryOptions } from '@tanstack/react-query'
import { api } from './client'

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
