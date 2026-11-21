import { useQuery } from '@tanstack/react-query'
import { ExternalLinkIcon, InfoIcon } from 'lucide-react'
import { useState } from 'react'
import { productQuery, useSiteLabel } from '@/api/queries'
import type { ProductDetail } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatDate, formatPrice } from '@/lib/format'
import { compareSizes } from '@/lib/sizes'
import { cn } from '@/lib/utils'
import { PriceChart } from './price-chart'
import { DiscountBadge, FavoriteButton } from './product-card'

export function ProductDrawer({
  productId,
  onClose,
}: {
  productId: number | undefined
  onClose: () => void
}) {
  return (
    <Sheet open={productId !== undefined} onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {productId !== undefined ? <DrawerBody productId={productId} /> : null}
      </SheetContent>
    </Sheet>
  )
}

function DrawerBody({ productId }: { productId: number }) {
  const { data, error, isPending } = useQuery(productQuery(productId))
  if (error) {
    return (
      <Alert variant="destructive" className="m-4">
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }
  if (isPending) {
    return (
      <div className="space-y-4 p-4">
        <SheetTitle className="sr-only">Loading item</SheetTitle>
        <Skeleton className="aspect-[2/3] w-full rounded-xl" />
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }
  // A new item gets a fresh Detail, so the selected image does not carry over.
  return <Detail key={data.id} product={data} />
}

function Detail({ product }: { product: ProductDetail }) {
  // The main image can repeat in the gallery; unique URLs also make stable React keys.
  const images = [
    ...new Map(
      [product.image, ...product.gallery].filter((i) => i !== null).map((i) => [i.thumb, i]),
    ).values(),
  ]
  const [active, setActive] = useState(0)
  const current = images[active] ?? images[0]
  const sizes = [...product.size_details].sort((a, b) => compareSizes(a.label, b.label))
  const site = useSiteLabel(product.site)

  return (
    <>
      <SheetHeader className="pr-12">
        <SheetTitle className="text-lg">{product.brand.name}</SheetTitle>
        <SheetDescription>{product.name}</SheetDescription>
      </SheetHeader>

      <div className="space-y-5 px-4 pb-6">
        {current ? (
          <div className="space-y-2">
            <div className="relative overflow-hidden rounded-xl bg-neutral-100">
              <img src={current.full} alt="" className="aspect-[2/3] w-full object-contain" />
              <FavoriteButton
                id={product.id}
                active={product.is_favorite}
                className="absolute top-3 right-3"
              />
            </div>
            {images.length > 1 ? (
              <div className="flex gap-2 overflow-x-auto p-1">
                {images.map((image, i) => (
                  <button
                    key={image.thumb}
                    type="button"
                    onClick={() => setActive(i)}
                    aria-label={`Image ${i + 1}`}
                    aria-current={i === active}
                    className={cn(
                      'w-16 shrink-0 overflow-hidden rounded-md bg-neutral-100',
                      i === active && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
                    )}
                  >
                    <img
                      src={image.thumb}
                      alt=""
                      loading="lazy"
                      className="aspect-[2/3] w-full object-contain"
                    />
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-2xl font-semibold">{formatPrice(product.price)}</span>
            <span className="text-muted-foreground line-through">
              {formatPrice(product.price_regular)}
            </span>
            <DiscountBadge pct={product.discount_pct} className="text-sm" />
          </div>
          <p className="text-sm text-emerald-700 dark:text-emerald-400">
            You save {formatPrice(product.savings)}
          </p>
          <HonestDiscount product={product} />
          {!product.is_active ? (
            <p className="text-sm font-medium text-destructive">No longer in the sale</p>
          ) : null}
        </div>

        {product.subtitle || product.color ? (
          <p className="text-sm text-muted-foreground">
            {[product.subtitle, product.color].filter(Boolean).join(' / ')}
          </p>
        ) : null}

        {product.category_paths.length ? (
          <div className="space-y-0.5 text-sm">
            {product.category_paths.map((path) => (
              <p key={path.map((c) => c.id).join('-')} className="text-muted-foreground">
                {path.map((c) => c.name).join(' > ')}
              </p>
            ))}
          </div>
        ) : null}

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Sizes</h3>
          <ul className="flex flex-wrap gap-1.5">
            {sizes.map((s) => (
              <li
                key={s.variation_id}
                title={
                  s.availability === 'LAST'
                    ? 'Last items'
                    : s.availability.replaceAll('_', ' ').toLowerCase()
                }
                className={cn(
                  'rounded-md border px-2 py-0.5 text-sm',
                  !s.in_stock && 'text-muted-foreground line-through opacity-60',
                  s.is_mine && s.in_stock && 'border-primary bg-primary text-primary-foreground',
                  s.availability === 'LAST' && 'border-amber-500',
                )}
              >
                {s.label}
              </li>
            ))}
          </ul>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Price history</h3>
          {product.price_history.length > 1 ? (
            <PriceChart
              history={product.price_history}
              until={product.is_active ? undefined : product.last_seen_at}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              No price changes since {formatDate(product.first_seen_at)}.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            In the sale since {formatDate(product.first_seen_at)}, last seen{' '}
            {formatDate(product.last_seen_at)}.
          </p>
        </section>

        <Button asChild className="w-full">
          <a href={product.url} target="_blank" rel="noreferrer">
            Open on {site.name} <ExternalLinkIcon />
          </a>
        </Button>
      </div>
    </>
  )
}

function HonestDiscount({ product }: { product: ProductDetail }) {
  if (product.price_min30 === null) return null
  const honest = product.discount_min30_pct ?? 0
  return (
    <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
      Lowest price in the last 30 days: {formatPrice(product.price_min30)} (
      {honest > 0 ? `-${honest}% from it` : 'not cheaper than that'})
      <Tooltip>
        <TooltipTrigger asChild>
          <InfoIcon className="size-3.5" aria-label="What is this?" />
        </TooltipTrigger>
        <TooltipContent className="max-w-64">
          The "honest" discount compares the current price with the lowest price of the previous 30
          days, not with the regular price. A discount that is only on paper shows 0 here.
        </TooltipContent>
      </Tooltip>
    </p>
  )
}
