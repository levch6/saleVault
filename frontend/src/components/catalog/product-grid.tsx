import { useInfiniteQuery } from '@tanstack/react-query'
import { LoaderCircleIcon, SearchXIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { productsQuery } from '@/api/queries'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import type { ApiCatalogQuery } from '@/lib/search'
import { ProductCard } from './product-card'

export const GRID =
  'grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(190px,1fr))] sm:gap-4'

export function ProductGrid({
  query,
  onOpen,
  onReset,
}: {
  query: ApiCatalogQuery
  onOpen: (id: number) => void
  onReset: () => void
}) {
  const {
    data,
    error,
    isPending,
    isFetching,
    isPlaceholderData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery(productsQuery(query))
  const sentinel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasNextPage) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '800px 0px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the catalog</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }
  if (isPending) {
    return (
      <div className={GRID}>
        {Array.from({ length: 10 }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
          <Skeleton key={i} className="aspect-[2/3.9] rounded-xl" />
        ))}
      </div>
    )
  }

  const items = data.pages.flatMap((p) => p.items)
  if (!items.length) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SearchXIcon />
          </EmptyMedia>
          <EmptyTitle>No items match</EmptyTitle>
          <EmptyDescription>Try fewer filters or a lower minimum discount.</EmptyDescription>
        </EmptyHeader>
        <Button variant="outline" onClick={onReset}>
          Reset filters
        </Button>
      </Empty>
    )
  }

  return (
    <div className={isPlaceholderData && isFetching ? 'opacity-60 transition-opacity' : undefined}>
      <div className={GRID}>
        {items.map((product) => (
          <ProductCard key={product.id} product={product} onOpen={onOpen} />
        ))}
      </div>
      <div ref={sentinel} className="flex h-20 items-center justify-center text-muted-foreground">
        {isFetchingNextPage ? <LoaderCircleIcon className="size-5 animate-spin" /> : null}
        {!hasNextPage && items.length > 12 ? <span className="text-sm">That's all.</span> : null}
      </div>
    </div>
  )
}
