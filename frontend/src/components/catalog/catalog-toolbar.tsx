import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { SearchIcon, SlidersHorizontalIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { settingsQuery } from '@/api/queries'
import type { Facets } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { formatCount } from '@/lib/format'
import { activeFilterCount, type CatalogSearch, DEFAULT_SORT, SORTS, type Sort } from '@/lib/search'
import { FilterSidebar, type OnChange } from './filter-sidebar'

function SearchBox({
  value,
  onChange,
}: {
  value: string | undefined
  onChange: (q: string | undefined) => void
}) {
  const [text, setText] = useState(value ?? '')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => setText(value ?? ''), [value])
  useEffect(() => {
    const next = text.trim() || undefined
    if (next === value) return
    const timer = setTimeout(() => onChange(next), 300)
    return () => clearTimeout(timer)
  }, [text, value, onChange])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (e.key === '/' && target?.tagName !== 'INPUT' && target?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="relative w-full sm:w-72">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        ref={input}
        type="search"
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
        placeholder="Search brand or name  ( / )"
        aria-label="Search"
        className="pl-8"
      />
    </div>
  )
}

function MySizesToggle({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (on: boolean) => void
}) {
  const { data } = useQuery(settingsQuery)
  const sizes = data?.my_sizes ?? []
  if (!sizes.length) {
    return (
      <Link to="/settings" className="text-sm text-primary underline-offset-4 hover:underline">
        Set my sizes
      </Link>
    )
  }
  return (
    <div className="flex items-center gap-2">
      <Switch id="my-sizes" checked={checked} onCheckedChange={onChange} />
      <Label htmlFor="my-sizes" className="cursor-pointer text-sm" title={sizes.join(', ')}>
        Only my sizes
      </Label>
    </div>
  )
}

export function CatalogToolbar({
  search,
  facets,
  detail,
  onChange,
  onReset,
}: {
  search: CatalogSearch
  facets: Facets | undefined
  detail: Facets | undefined
  onChange: OnChange
  onReset: () => void
}) {
  const [filtersOpen, setFiltersOpen] = useState(false)
  const active = activeFilterCount(search)
  return (
    <div className="flex flex-wrap items-center gap-3">
      <SearchBox value={search.q} onChange={(q) => onChange({ q })} />
      <span className="text-sm text-muted-foreground tabular-nums">
        {facets ? `${formatCount(facets.total)} items` : ''}
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-3">
        <MySizesToggle
          checked={search.my_sizes ?? false}
          onChange={(on) => onChange({ my_sizes: on || undefined })}
        />
        <Select
          value={search.sort ?? DEFAULT_SORT}
          onValueChange={(v) => onChange({ sort: v === DEFAULT_SORT ? undefined : (v as Sort) })}
        >
          <SelectTrigger className="w-48" aria-label="Sort">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORTS.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" className="lg:hidden" onClick={() => setFiltersOpen(true)}>
          <SlidersHorizontalIcon /> Filters{active ? ` (${active})` : ''}
        </Button>
        {active ? (
          <Button variant="ghost" onClick={onReset}>
            Reset all
          </Button>
        ) : null}
      </div>
      <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
        <SheetContent side="left" className="w-80 overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-6">
            <FilterSidebar search={search} facets={facets} detail={detail} onChange={onChange} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
