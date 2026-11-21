import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { PackageSearchIcon } from 'lucide-react'
import { useCallback } from 'react'
import { facetsQuery, sitesQuery } from '@/api/queries'
import { CatalogToolbar } from '@/components/catalog/catalog-toolbar'
import { FilterSidebar } from '@/components/catalog/filter-sidebar'
import { ProductDrawer } from '@/components/catalog/product-drawer'
import { ProductGrid } from '@/components/catalog/product-grid'
import { RefreshMenu } from '@/components/runs/run-controls'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import {
  activeFilterCount,
  type CatalogSearch,
  compact,
  toApiQuery,
  toFacetQuery,
  validateCatalogSearch,
} from '@/lib/search'

export const Route = createFileRoute('/')({
  validateSearch: validateCatalogSearch,
  component: CatalogPage,
})

function CatalogPage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: '/' })
  // Cheap facets first (list-speed), categories and sizes in a second, slower request.
  const facets = useQuery(facetsQuery(toFacetQuery(search), false))
  const detail = useQuery(facetsQuery(toFacetQuery(search)))
  const sites = useQuery(sitesQuery)

  const update = useCallback(
    (patch: Partial<CatalogSearch>) =>
      navigate({
        search: (prev) => compact({ ...prev, ...patch, product: undefined }),
        replace: true,
      }),
    [navigate],
  )
  const reset = useCallback(
    () => navigate({ search: (prev) => compact({ sort: prev.sort }), replace: true }),
    [navigate],
  )
  const open = useCallback(
    (id: number) => navigate({ search: (prev) => ({ ...prev, product: id }), resetScroll: false }),
    [navigate],
  )
  const close = useCallback(
    () =>
      navigate({
        search: (prev) => compact({ ...prev, product: undefined }),
        resetScroll: false,
        replace: true,
      }),
    [navigate],
  )

  const neverScraped =
    sites.data?.every((s) => s.last_completed === null) === true &&
    facets.data?.total === 0 &&
    activeFilterCount(search) === 0
  if (neverScraped && sites.data) {
    return (
      <Empty className="mt-16 border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PackageSearchIcon />
          </EmptyMedia>
          <EmptyTitle>No data yet</EmptyTitle>
          <EmptyDescription>
            Run the first scrape to fill the catalog. It takes a few minutes; a browser window may
            appear while it runs.
          </EmptyDescription>
        </EmptyHeader>
        <RefreshMenu sites={sites.data} label="Run first scrape" />
      </Empty>
    )
  }

  return (
    <div className="flex gap-6">
      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="sticky top-20 max-h-[calc(100svh-6rem)] overflow-y-auto pr-2 pb-8">
          <FilterSidebar
            search={search}
            facets={facets.data}
            detail={detail.data}
            onChange={update}
          />
        </div>
      </aside>
      <section className="min-w-0 flex-1 space-y-4">
        <CatalogToolbar
          search={search}
          facets={facets.data}
          detail={detail.data}
          onChange={update}
          onReset={reset}
        />
        <ProductGrid
          query={toApiQuery(compact({ ...search, product: undefined }))}
          onOpen={open}
          onReset={reset}
        />
      </section>
      <ProductDrawer productId={search.product} onClose={close} />
    </div>
  )
}
