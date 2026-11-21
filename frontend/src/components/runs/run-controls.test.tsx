import { act, screen, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { describe, expect, it, vi } from 'vitest'
import type { SiteOut } from '@/api/types'
import { mockApi, newClient, renderWithClient, run, site } from '@/test/utils'
import { RunControls, runSummary } from './run-controls'

const prm = site()
const answear = site({
  code: 'answear_ua',
  name: 'Answear.ua',
  active_products: 0,
  last_completed: null,
  latest: null,
})
const runningAnswear = site({
  ...answear,
  latest: run({
    id: 9,
    site: 'answear_ua',
    status: 'running',
    finished_at: null,
    pages_total: 100,
    pages_done: 12,
    items_seen: 1234,
  }),
})

function renderControls(sites: SiteOut[]) {
  const calls = mockApi({
    'GET /api/sites': sites,
    'POST /api/runs': { run_ids: [21, 22] },
    'POST /api/runs/9/cancel': run({ id: 9, status: 'running' }),
  })
  const client = newClient()
  client.setQueryData(['sites'], sites)
  return { ...renderWithClient(<RunControls />, client), calls }
}

describe('runSummary', () => {
  it('sums up a finished run', () => {
    expect(runSummary('PRM', run())).toBe('PRM: 100 items, 5 new, 3 cheaper, 2 removed')
  })
})

describe('RunControls', () => {
  it('shows every shop, including one that was never scraped', () => {
    renderControls([prm, answear])

    expect(screen.getByText('PRM')).toBeInTheDocument()
    expect(screen.getByText('Answear.ua')).toBeInTheDocument()
    expect(screen.getByText('never scraped')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
  })

  it('shows the progress of a running shop and cancels it', async () => {
    const { user, calls } = renderControls([prm, runningAnswear])

    expect(screen.getByText(/12\/100 pages, 1,234 items/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel Answear.ua run' }))

    await waitFor(() =>
      expect(calls).toContainEqual(
        expect.objectContaining({ method: 'POST', path: '/api/runs/9/cancel' }),
      ),
    )
  })

  it('starts all shops from the refresh menu', async () => {
    const { user, calls } = renderControls([prm, answear])

    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await user.click(await screen.findByRole('menuitem', { name: 'All shops' }))

    await waitFor(() =>
      expect(calls).toContainEqual({ method: 'POST', path: '/api/runs', body: { site: 'all' } }),
    )
  })

  it('announces a run that finished', async () => {
    const success = vi.spyOn(toast, 'success')
    const running = site({ latest: run({ id: 5, status: 'running', finished_at: null }) })
    const { client } = renderControls([running])
    expect(screen.getByText(/pages/)).toBeInTheDocument()

    act(() => client.setQueryData(['sites'], [site({ latest: run({ id: 5 }) })]))

    await waitFor(() =>
      expect(success).toHaveBeenCalledWith('PRM: 100 items, 5 new, 3 cheaper, 2 removed.'),
    )
  })
})
