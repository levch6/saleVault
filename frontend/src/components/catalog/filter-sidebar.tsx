import { ChevronRightIcon } from 'lucide-react'
import { type ReactNode, useMemo, useState } from 'react'
import type { CategoryFacet, Facets } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { formatCount } from '@/lib/format'
import { type CatalogSearch, type Flag, type Gender, toggled } from '@/lib/search'
import { groupSizes } from '@/lib/sizes'
import { cn } from '@/lib/utils'

export type OnChange = (patch: Partial<CatalogSearch>) => void

const DISCOUNT_PRESETS = [0, 30, 50, 60, 70]
const FLAG_LABELS: Record<Flag, string> = {
  new: 'New since last run',
  price_drop: 'Got cheaper',
  favorite: 'Favorites',
}
const BRANDS_COLLAPSED = 12

function Section({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="space-y-2 border-b pb-4 last:border-b-0">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function SectionLoading({ title }: { title: string }) {
  return (
    <Section title={title}>
      <div className="h-16 animate-pulse rounded-md bg-muted" />
    </Section>
  )
}

function Clear({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs text-muted-foreground hover:text-foreground"
    >
      Clear
    </button>
  )
}

function CheckRow({
  checked,
  onToggle,
  label,
  count,
  id,
}: {
  checked: boolean
  onToggle: () => void
  label: string
  count?: number
  id: string
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Checkbox id={id} checked={checked} onCheckedChange={onToggle} />
      <label htmlFor={id} className="flex min-w-0 flex-1 cursor-pointer justify-between gap-2">
        <span className="truncate">{label}</span>
        {count !== undefined ? (
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {formatCount(count)}
          </span>
        ) : null}
      </label>
    </div>
  )
}

export function FilterSidebar({
  search,
  facets,
  detail,
  onChange,
}: {
  search: CatalogSearch
  /** Cheap facets (heavy=false). */
  facets: Facets | undefined
  /** Full facets: sizes come from here once ready. */
  detail: Facets | undefined
  onChange: OnChange
}) {
  if (!facets) return <div className="h-96 animate-pulse rounded-xl bg-muted" />
  return (
    <div className="space-y-4">
      {facets.sites.length > 1 ? (
        <Section
          title="Shop"
          action={search.site ? <Clear onClick={() => onChange({ site: undefined })} /> : null}
        >
          {facets.sites.map((s) => (
            <CheckRow
              key={s.value}
              id={`site-${s.value}`}
              label={s.label}
              count={s.count}
              checked={search.site?.includes(s.value) ?? false}
              onToggle={() => onChange({ site: toggled(search.site, s.value) })}
            />
          ))}
        </Section>
      ) : null}

      <Section title="Gender">
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant={search.gender ? 'outline' : 'default'}
            onClick={() => onChange({ gender: undefined })}
          >
            All
          </Button>
          {facets.genders
            .filter((g) => g.count > 0 || search.gender?.includes(g.value as Gender))
            .map((g) => {
              const active = search.gender?.length === 1 && search.gender[0] === g.value
              return (
                <Button
                  key={g.value}
                  size="sm"
                  variant={active ? 'default' : 'outline'}
                  onClick={() => onChange({ gender: active ? undefined : [g.value as Gender] })}
                >
                  {g.label}
                  <span className="text-xs opacity-70 tabular-nums">{formatCount(g.count)}</span>
                </Button>
              )
            })}
        </div>
      </Section>

      <Section title="Discount">
        <div className="flex flex-wrap gap-1.5">
          {DISCOUNT_PRESETS.map((pct) => {
            const active = (search.discount_min ?? 0) === pct
            return (
              <Button
                key={pct}
                size="sm"
                variant={active ? 'default' : 'outline'}
                onClick={() => onChange({ discount_min: pct || undefined })}
              >
                {pct ? `${pct}%+` : 'Any'}
              </Button>
            )
          })}
        </div>
        {facets.discount.max !== null ? (
          <p className="text-xs text-muted-foreground">Up to -{facets.discount.max}% right now</p>
        ) : null}
      </Section>

      <PriceSection search={search} facets={facets} onChange={onChange} />

      <Section title="Show only">
        {(['new', 'price_drop', 'favorite'] as const).map((flag) => (
          <CheckRow
            key={flag}
            id={`flag-${flag}`}
            label={FLAG_LABELS[flag]}
            checked={search.flags?.includes(flag) ?? false}
            onToggle={() => onChange({ flags: toggled(search.flags, flag) })}
          />
        ))}
      </Section>

      {facets.categories.length ? (
        <CategorySection search={search} categories={facets.categories} onChange={onChange} />
      ) : null}
      <BrandSection search={search} facets={facets} onChange={onChange} />
      {detail?.sizes ? (
        <SizeSection search={search} sizes={detail.sizes} onChange={onChange} />
      ) : (
        <SectionLoading title="Size in stock" />
      )}
    </div>
  )
}

function PriceSection({
  search,
  facets,
  onChange,
}: {
  search: CatalogSearch
  facets: Facets
  onChange: OnChange
}) {
  const commit = (key: 'price_min' | 'price_max', raw: string) => {
    const value = raw.trim() === '' ? undefined : Math.max(0, Math.round(Number(raw)))
    if (value !== undefined && !Number.isFinite(value)) return
    onChange(key === 'price_min' ? { price_min: value } : { price_max: value })
  }
  const field = (key: 'price_min' | 'price_max', placeholder: number | null) => (
    <Input
      key={`${key}-${search[key] ?? ''}`}
      type="number"
      inputMode="numeric"
      min={0}
      aria-label={key === 'price_min' ? 'Minimum price' : 'Maximum price'}
      placeholder={placeholder !== null ? String(placeholder) : ''}
      defaultValue={search[key] ?? ''}
      onBlur={(e) => commit(key, e.currentTarget.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit(key, e.currentTarget.value)
      }}
    />
  )
  return (
    <Section
      title="Price, UAH"
      action={
        search.price_min !== undefined || search.price_max !== undefined ? (
          <Clear onClick={() => onChange({ price_min: undefined, price_max: undefined })} />
        ) : null
      }
    >
      <div className="flex items-center gap-2">
        {field('price_min', facets.price.min)}
        <span className="text-muted-foreground">-</span>
        {field('price_max', facets.price.max)}
      </div>
    </Section>
  )
}

interface TreeNode {
  category: CategoryFacet
  children: TreeNode[]
}

function buildTree(categories: readonly CategoryFacet[]): TreeNode[] {
  const nodes = new Map(categories.map((c) => [c.id, { category: c, children: [] as TreeNode[] }]))
  const roots: TreeNode[] = []
  for (const node of nodes.values()) {
    const parent = node.category.parent_id === null ? undefined : nodes.get(node.category.parent_id)
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

function CategorySection({
  search,
  categories,
  onChange,
}: {
  search: CatalogSearch
  categories: readonly CategoryFacet[]
  onChange: OnChange
}) {
  const tree = useMemo(() => buildTree(categories), [categories])
  const selected = new Set(search.category ?? [])
  return (
    <Section
      title="Category"
      action={search.category ? <Clear onClick={() => onChange({ category: undefined })} /> : null}
    >
      <ul className="space-y-0.5">
        {tree.map((node) => (
          <CategoryNode
            key={node.category.id}
            node={node}
            selected={selected}
            onToggle={(id) => onChange({ category: toggled(search.category, id) })}
          />
        ))}
      </ul>
    </Section>
  )
}

function containsSelected(node: TreeNode, selected: Set<string>): boolean {
  return node.children.some((c) => selected.has(c.category.id) || containsSelected(c, selected))
}

function CategoryNode({
  node,
  selected,
  onToggle,
}: {
  node: TreeNode
  selected: Set<string>
  onToggle: (id: string) => void
}) {
  const [open, setOpen] = useState(() => containsSelected(node, selected))
  const { category, children } = node
  return (
    <li>
      <div className="flex items-center gap-1">
        {children.length ? (
          <button
            type="button"
            aria-label={open ? `Collapse ${category.name}` : `Expand ${category.name}`}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="grid size-5 place-items-center text-muted-foreground"
          >
            <ChevronRightIcon className={cn('size-3.5 transition', open && 'rotate-90')} />
          </button>
        ) : (
          <span className="size-5" />
        )}
        <div className="min-w-0 flex-1">
          <CheckRow
            id={`cat-${category.id}`}
            label={category.name}
            count={category.count}
            checked={selected.has(category.id)}
            onToggle={() => onToggle(category.id)}
          />
        </div>
      </div>
      {open && children.length ? (
        <ul className="ml-4 space-y-0.5 border-l pl-1">
          {children.map((child) => (
            <CategoryNode
              key={child.category.id}
              node={child}
              selected={selected}
              onToggle={onToggle}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function BrandSection({
  search,
  facets,
  onChange,
}: {
  search: CatalogSearch
  facets: Facets
  onChange: OnChange
}) {
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState(false)
  const selected = new Set(search.brand ?? [])
  const needle = filter.trim().toLowerCase()
  const matching = facets.brands.filter((b) => !needle || b.name.toLowerCase().includes(needle))
  const ordered = [
    ...matching.filter((b) => selected.has(b.id)),
    ...matching.filter((b) => !selected.has(b.id)),
  ]
  const visible =
    expanded || needle ? ordered : ordered.slice(0, Math.max(BRANDS_COLLAPSED, selected.size))
  return (
    <Section
      title="Brand"
      action={search.brand ? <Clear onClick={() => onChange({ brand: undefined })} /> : null}
    >
      <Input
        placeholder={`Search ${facets.brands.length} brands`}
        value={filter}
        onChange={(e) => setFilter(e.currentTarget.value)}
        aria-label="Search brands"
      />
      <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
        {visible.map((b) => (
          <CheckRow
            key={b.id}
            id={`brand-${b.id}`}
            label={b.name}
            count={b.count}
            checked={selected.has(b.id)}
            onToggle={() => onChange({ brand: toggled(search.brand, b.id) })}
          />
        ))}
      </div>
      {!needle && ordered.length > visible.length ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-xs text-primary hover:underline"
        >
          Show all {ordered.length}
        </button>
      ) : null}
    </Section>
  )
}

function SizeSection({
  search,
  sizes,
  onChange,
}: {
  search: CatalogSearch
  sizes: NonNullable<Facets['sizes']>
  onChange: OnChange
}) {
  const groups = useMemo(() => groupSizes(sizes), [sizes])
  const selected = new Set(search.size ?? [])
  return (
    <Section
      title="Size in stock"
      action={search.size ? <Clear onClick={() => onChange({ size: undefined })} /> : null}
    >
      {(['letters', 'numbers', 'other'] as const).map((group) =>
        groups[group].length ? (
          <div key={group} className="flex flex-wrap gap-1">
            {groups[group].map((s) => (
              <button
                key={s.label}
                type="button"
                aria-pressed={selected.has(s.label)}
                onClick={() => onChange({ size: toggled(search.size, s.label) })}
                title={`${formatCount(s.count)} items`}
                className={cn(
                  'rounded-md border px-2 py-0.5 text-xs transition hover:border-foreground/40',
                  selected.has(s.label) && 'border-primary bg-primary text-primary-foreground',
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        ) : null,
      )}
    </Section>
  )
}
