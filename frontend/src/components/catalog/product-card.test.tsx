import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ProductCard as Card, SiteOut } from '@/api/types'
import { formatPrice } from '@/lib/format'
import { mockApi, noContent, product, renderWithClient, site } from '@/test/utils'
import { ProductCard } from './product-card'

function renderCard(item: Card, sites: SiteOut[] = [site()]) {
  const calls = mockApi({
    'GET /api/sites': sites,
    'PUT /api/favorites/7': noContent,
    'DELETE /api/favorites/7': noContent,
  })
  const onOpen = vi.fn()
  return { ...renderWithClient(<ProductCard product={item} onOpen={onOpen} />), calls, onOpen }
}

/** Prices use non-breaking spaces; Testing Library collapses the ones in the page. */
const price = (value: number) => formatPrice(value).replace(/\s+/g, ' ')

const sizes = (labels: string[], inStock = true) =>
  labels.map((label) => ({ label, in_stock: inStock, is_mine: false }))

describe('ProductCard', () => {
  it('shows the discount, the prices and the savings', () => {
    renderCard(product())

    expect(screen.getByText('-60%')).toBeInTheDocument()
    expect(screen.getByText(price(1200))).toBeInTheDocument()
    expect(screen.getByText(price(3000))).toBeInTheDocument()
    expect(screen.getByText(`-${price(1800)}`)).toBeInTheDocument()
  })

  it('lists only sizes in stock, in size order', () => {
    renderCard(product({ sizes: [...sizes(['L', 'S', 'XS']), ...sizes(['M'], false)] }))

    const list = screen.getByRole('list', { name: 'Sizes in stock' })
    const shown = within(list)
      .getAllByRole('listitem')
      .map((li) => li.textContent)
    expect(shown).toEqual(['XS', 'S', 'L'])
  })

  it('collapses sizes beyond seven into a counter', () => {
    renderCard(product({ sizes: sizes(['36', '37', '38', '39', '40', '41', '42', '43', '44']) }))

    const list = screen.getByRole('list', { name: 'Sizes in stock' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(8)
    expect(within(list).getByText('+2')).toBeInTheDocument()
  })

  it('marks new, cheaper and inactive items', () => {
    renderCard(product({ badges: ['new', 'price_drop'], prev_price: 1500, is_active: false }))

    expect(screen.getByText('NEW')).toBeInTheDocument()
    expect(screen.getByText('cheaper').closest('[title]')).toHaveAttribute(
      'title',
      `was ${formatPrice(1500)}`,
    )
    expect(screen.getByText('Not in sale')).toBeInTheDocument()
  })

  it('shows no badges for a plain item', () => {
    renderCard(product({ badges: ['price_drop'], prev_price: null }))

    expect(screen.queryByText('NEW')).not.toBeInTheDocument()
    expect(screen.queryByText('cheaper')).not.toBeInTheDocument()
    expect(screen.queryByText('Not in sale')).not.toBeInTheDocument()
  })

  it('names the shop only when several shops have items', async () => {
    const { unmount, calls } = renderCard(product())
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(screen.queryByText('PRM')).not.toBeInTheDocument()
    unmount()

    renderCard(product(), [site(), site({ code: 'answear_ua', name: 'Answear.ua' })])

    expect(await screen.findByText('PRM')).toBeInTheDocument()
  })

  it('opens the item from its picture', async () => {
    const { user, onOpen } = renderCard(product())

    await user.click(screen.getByRole('button', { name: 'Open Acme Wool coat' }))

    expect(onOpen).toHaveBeenCalledWith(7)
  })

  it('adds the item to favorites', async () => {
    const { user, calls } = renderCard(product())

    const star = screen.getByRole('button', { name: 'Add to favorites' })
    expect(star).toHaveAttribute('aria-pressed', 'false')
    await user.click(star)

    await waitFor(() =>
      expect(calls).toContainEqual(
        expect.objectContaining({ method: 'PUT', path: '/api/favorites/7' }),
      ),
    )
  })

  it('removes a favorite', async () => {
    const { user, calls } = renderCard(product({ is_favorite: true }))

    const star = screen.getByRole('button', { name: 'Remove from favorites' })
    expect(star).toHaveAttribute('aria-pressed', 'true')
    await user.click(star)

    await waitFor(() =>
      expect(calls).toContainEqual(
        expect.objectContaining({ method: 'DELETE', path: '/api/favorites/7' }),
      ),
    )
  })
})
