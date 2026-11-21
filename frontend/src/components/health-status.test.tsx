import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { HealthStatus } from './health-status'

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('HealthStatus', () => {
  it('shows the backend version when the API is up', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ status: 'ok', version: '1.2.3' })),
    )

    renderWithQuery(<HealthStatus />)

    expect(await screen.findByText('API online, v1.2.3')).toBeInTheDocument()
  })

  it('shows offline when the API responds with an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('bad gateway', { status: 502 })),
    )

    renderWithQuery(<HealthStatus />)

    expect(await screen.findByText('API offline')).toBeInTheDocument()
  })
})
