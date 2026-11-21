import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogSearch } from '@/lib/search'
import { facets, mockApi, newClient, renderWithClient } from '@/test/utils'
import { CatalogToolbar } from './catalog-toolbar'

function renderToolbar(search: CatalogSearch = {}) {
  mockApi({ 'GET /api/settings': { my_sizes: ['M', '42'] } })
  const client = newClient()
  // Saved sizes are known up front, as after the first load of the app.
  client.setQueryData(['settings'], { my_sizes: ['M', '42'] })
  const onChange = vi.fn()
  const onReset = vi.fn()
  const view = renderWithClient(
    <CatalogToolbar
      search={search}
      facets={facets()}
      detail={undefined}
      onChange={onChange}
      onReset={onReset}
    />,
    client,
  )
  return { ...view, onChange, onReset }
}

describe('CatalogToolbar', () => {
  it('searches once the user stops typing', async () => {
    const { user, onChange } = renderToolbar()

    await user.type(screen.getByRole('searchbox', { name: 'Search' }), 'wool coat')

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ q: 'wool coat' }))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('shows the number of matching items', () => {
    renderToolbar()

    expect(screen.getByText('1,234 items')).toBeInTheDocument()
  })

  it('offers a reset only while filters are active', async () => {
    const { unmount } = renderToolbar()
    expect(screen.queryByRole('button', { name: 'Reset all' })).not.toBeInTheDocument()
    unmount()

    const { user, onReset } = renderToolbar({ brand: [1], discount_min: 50 })
    expect(screen.getByRole('button', { name: /Filters \(2\)/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reset all' }))

    expect(onReset).toHaveBeenCalledOnce()
  })

  it('switches to my sizes and back', async () => {
    const { user, onChange, unmount } = renderToolbar()
    await user.click(screen.getByRole('switch', { name: 'Only my sizes' }))
    expect(onChange).toHaveBeenLastCalledWith({ my_sizes: true })
    unmount()

    const second = renderToolbar({ my_sizes: true })
    await second.user.click(screen.getByRole('switch', { name: 'Only my sizes' }))
    expect(second.onChange).toHaveBeenLastCalledWith({ my_sizes: undefined })
  })
})
