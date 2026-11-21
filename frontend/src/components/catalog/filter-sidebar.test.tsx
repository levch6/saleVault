import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Facets } from '@/api/types'
import type { CatalogSearch } from '@/lib/search'
import { facets } from '@/test/utils'
import { FilterSidebar } from './filter-sidebar'

function renderSidebar({
  search = {},
  cheap = facets(),
  detail,
}: {
  search?: CatalogSearch
  cheap?: Facets
  detail?: Facets
} = {}) {
  const onChange = vi.fn()
  const user = userEvent.setup()
  const view = render(
    <FilterSidebar search={search} facets={cheap} detail={detail} onChange={onChange} />,
  )
  return { ...view, onChange, user }
}

const full = facets({
  categories: [
    { id: 10, name: 'Clothes', parent_id: null, depth: 0, count: 90 },
    { id: 11, name: 'Coats', parent_id: 10, depth: 1, count: 40 },
    { id: 12, name: 'Parkas', parent_id: 11, depth: 2, count: 15 },
  ],
  sizes: [
    { label: 'M', count: 50 },
    { label: '42', count: 20 },
  ],
})

describe('FilterSidebar', () => {
  it('shows a placeholder until the facets arrive', () => {
    render(<FilterSidebar search={{}} facets={undefined} detail={undefined} onChange={vi.fn()} />)

    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })

  it('keeps placeholders for categories and sizes until the full facets load', () => {
    const { rerender, onChange } = renderSidebar()

    expect(screen.getByRole('heading', { name: 'Category' })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /^Clothes/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'M' })).not.toBeInTheDocument()

    rerender(<FilterSidebar search={{}} facets={facets()} detail={full} onChange={onChange} />)

    expect(screen.getByRole('checkbox', { name: /^Clothes/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'M' })).toBeInTheDocument()
  })

  it('offers the shop filter only when there are several shops', () => {
    renderSidebar()
    expect(screen.queryByRole('heading', { name: 'Shop' })).not.toBeInTheDocument()
  })

  it('toggles shops', async () => {
    const sites = [
      { value: 'prm', label: 'PRM', count: 1234 },
      { value: 'answear_ua', label: 'Answear.ua', count: 9000 },
    ]
    const { user, onChange } = renderSidebar({
      search: { site: ['prm'] },
      cheap: facets({ sites }),
    })

    expect(screen.getByRole('checkbox', { name: /^PRM/ })).toBeChecked()
    await user.click(screen.getByRole('checkbox', { name: /^Answear\.ua/ }))

    expect(onChange).toHaveBeenCalledWith({ site: ['prm', 'answear_ua'] })
  })

  it('selects one gender at a time and hides empty ones', async () => {
    const { user, onChange } = renderSidebar()

    expect(screen.queryByRole('button', { name: /^Home/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Women/ }))

    expect(onChange).toHaveBeenLastCalledWith({ gender: ['women'] })
  })

  it('clears the gender when the active one is clicked again', async () => {
    const { user, onChange } = renderSidebar({ search: { gender: ['women'] } })

    await user.click(screen.getByRole('button', { name: /^Women/ }))

    expect(onChange).toHaveBeenLastCalledWith({ gender: undefined })
  })

  it('applies discount presets', async () => {
    const { user, onChange } = renderSidebar({ search: { discount_min: 30 } })

    await user.click(screen.getByRole('button', { name: '50%+' }))
    expect(onChange).toHaveBeenLastCalledWith({ discount_min: 50 })

    await user.click(screen.getByRole('button', { name: 'Any' }))
    expect(onChange).toHaveBeenLastCalledWith({ discount_min: undefined })
  })

  it('commits prices on Enter, clamps negatives and clears empty fields', async () => {
    const { user, onChange } = renderSidebar({ search: { price_max: 5000 } })

    await user.type(screen.getByRole('spinbutton', { name: 'Minimum price' }), '1500{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({ price_min: 1500 })

    const max = screen.getByRole('spinbutton', { name: 'Maximum price' })
    await user.clear(max)
    await user.type(max, '-5{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({ price_max: 0 })

    await user.clear(max)
    await user.tab()
    expect(onChange).toHaveBeenLastCalledWith({ price_max: undefined })
  })

  it('filters brands by name and keeps selected ones on top', async () => {
    const brands = Array.from({ length: 14 }, (_, i) => ({
      id: i + 1,
      name: `Brand ${String.fromCharCode(65 + i)}`,
      count: 100 - i,
    }))
    const { user } = renderSidebar({ search: { brand: [14] }, cheap: facets({ brands }) })

    const shown = () => screen.getAllByRole('checkbox', { name: /^Brand / })
    expect(shown()).toHaveLength(12)
    expect(shown()[0]).toHaveAccessibleName(/^Brand N/)
    expect(shown()[0]).toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Show all 14' }))
    expect(shown()).toHaveLength(14)

    await user.type(screen.getByRole('textbox', { name: 'Search brands' }), 'brand c')
    expect(shown()).toHaveLength(1)
    expect(shown()[0]).toHaveAccessibleName(/^Brand C/)
  })

  it('expands the category tree on demand', async () => {
    const { user, onChange } = renderSidebar({ detail: full })

    expect(screen.queryByRole('checkbox', { name: /^Coats/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Expand Clothes' }))
    await user.click(screen.getByRole('checkbox', { name: /^Coats/ }))

    expect(onChange).toHaveBeenCalledWith({ category: [11] })
  })

  it('opens the branches that lead to a selected category', () => {
    renderSidebar({ search: { category: [12] }, detail: full })

    expect(screen.getByRole('checkbox', { name: /^Parkas/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Collapse Clothes' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('toggles sizes in stock', async () => {
    const { user, onChange } = renderSidebar({ search: { size: ['42'] }, detail: full })

    expect(screen.getByRole('button', { name: '42' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'M' }))

    expect(onChange).toHaveBeenCalledWith({ size: ['42', 'M'] })
  })

  it('toggles the show-only flags', async () => {
    const { user, onChange } = renderSidebar()

    await user.click(screen.getByRole('checkbox', { name: 'Got cheaper' }))

    expect(onChange).toHaveBeenCalledWith({ flags: ['price_drop'] })
  })
})
