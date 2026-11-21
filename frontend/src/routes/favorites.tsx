import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { StarIcon } from 'lucide-react'
import { favoritesQuery } from '@/api/queries'
import type { FavoriteOut } from '@/api/types'
import { ProductCard } from '@/components/catalog/product-card'
import { ProductDrawer } from '@/components/catalog/product-drawer'
import { GRID } from '@/components/catalog/product-grid'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatPrice } from '@/lib/format'
import { compact } from '@/lib/search'
import { cn } from '@/lib/utils'

const SHOW = ['all', 'active', 'gone'] as const
type Show = (typeof SHOW)[number]
const SHOW_LABELS: Record<Show, string> = { all: 'All', active: 'In sale', gone: 'Not in sale' }

interface FavoritesSearch {
  show?: Show
  product?: number
}

export const Route = createFileRoute('/favorites')({
  validateSearch: (raw: Record<string, unknown>): FavoritesSearch => {
    const show = SHOW.find((s) => s === raw.show)
    const product = Number(raw.product)
    return compact({
      show: show === 'all' ? undefined : show,
      product: Number.isInteger(product) && product > 0 ? product : undefined,
    })
  },
  component: FavoritesPage,
})

function PriceChange({ favorite }: { favorite: FavoriteOut }) {
  const change = favorite.price_change
  const pct = favorite.price_at_add ? Math.round((change / favorite.price_at_add) * 100) : 0
  return (
    <p className="text-xs text-muted-foreground">
      Added {formatDate(favorite.added_at)}:{' '}
      <span
        className={cn(
          'font-medium',
          change < 0 && 'text-emerald-700 dark:text-emerald-400',
          change > 0 && 'text-destructive',
        )}
      >
        {change === 0
          ? 'same price'
          : `${change < 0 ? '' : '+'}${formatPrice(change)} (${pct > 0 ? '+' : ''}${pct}%)`}
      </span>
    </p>
  )
}

function FavoritesPage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: '/favorites' })
  const { data, isPending } = useQuery(favoritesQuery)
  const show = search.show ?? 'all'
  const shown = (data ?? []).filter(
    (f) => show === 'all' || (show === 'active' ? f.product.is_active : !f.product.is_active),
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Favorites</h1>
        <div className="flex gap-1.5">
          {SHOW.map((s) => (
            <Button
              key={s}
              size="sm"
              variant={s === show ? 'default' : 'outline'}
              onClick={() =>
                navigate({
                  search: (prev) => compact({ ...prev, show: s === 'all' ? undefined : s }),
                  replace: true,
                })
              }
            >
              {SHOW_LABELS[s]}
            </Button>
          ))}
        </div>
      </div>

      {isPending ? (
        <div className={GRID}>
          {Array.from({ length: 5 }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
            <Skeleton key={i} className="aspect-[2/3.9] rounded-xl" />
          ))}
        </div>
      ) : shown.length ? (
        <div className={GRID}>
          {shown.map((f) => (
            <ProductCard
              key={f.product.id}
              product={f.product}
              onOpen={(id) =>
                navigate({ search: (prev) => ({ ...prev, product: id }), resetScroll: false })
              }
              footer={<PriceChange favorite={f} />}
            />
          ))}
        </div>
      ) : (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <StarIcon />
            </EmptyMedia>
            <EmptyTitle>{data?.length ? 'Nothing here' : 'No favorites yet'}</EmptyTitle>
            <EmptyDescription>
              Star items in the catalog to follow their price; changes since you added them show up
              here.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      <ProductDrawer
        productId={search.product}
        onClose={() =>
          navigate({
            search: (prev) => compact({ ...prev, product: undefined }),
            replace: true,
            resetScroll: false,
          })
        }
      />
    </div>
  )
}
