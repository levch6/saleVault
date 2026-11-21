import { ExternalLinkIcon, StarIcon, TrendingDownIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useSiteLabel, useToggleFavorite } from '@/api/queries'
import type { ProductCard as Card } from '@/api/types'
import { discountTone, formatPrice } from '@/lib/format'
import { compareSizes } from '@/lib/sizes'
import { cn } from '@/lib/utils'

const MAX_SIZES = 7

export function DiscountBadge({ pct, className }: { pct: number; className?: string }) {
  return (
    <span
      className={cn(
        'rounded-md px-1.5 py-0.5 text-xs font-semibold tabular-nums',
        discountTone(pct),
        className,
      )}
    >
      -{pct}%
    </span>
  )
}

export function FavoriteButton({
  id,
  active,
  className,
}: {
  id: number
  active: boolean
  className?: string
}) {
  const toggle = useToggleFavorite()
  return (
    <button
      type="button"
      aria-label={active ? 'Remove from favorites' : 'Add to favorites'}
      aria-pressed={active}
      onClick={() => toggle.mutate({ id, favorite: !active })}
      className={cn(
        'grid size-8 place-items-center rounded-full bg-background/80 backdrop-blur transition hover:scale-110',
        className,
      )}
    >
      <StarIcon
        className={cn('size-4', active ? 'fill-amber-400 text-amber-500' : 'text-foreground/70')}
      />
    </button>
  )
}

export function ProductCard({
  product,
  onOpen,
  footer,
}: {
  product: Card
  onOpen: (id: number) => void
  footer?: ReactNode
}) {
  const site = useSiteLabel(product.site)
  const inStock = product.sizes
    .filter((s) => s.in_stock)
    .sort((a, b) => compareSizes(a.label, b.label))
  const shown = inStock.slice(0, MAX_SIZES)

  return (
    <article
      className={cn(
        'group relative flex flex-col overflow-hidden rounded-xl border bg-card text-card-foreground',
        !product.is_active && 'opacity-60',
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(product.id)}
        className="relative block aspect-[2/3] overflow-hidden bg-muted"
        aria-label={`Open ${product.brand.name} ${product.name}`}
      >
        {product.image ? (
          <img
            src={product.image.thumb}
            alt=""
            loading="lazy"
            decoding="async"
            className="size-full object-cover transition duration-300 group-hover:scale-[1.03]"
          />
        ) : null}
        <span className="absolute top-2 left-2 flex flex-col items-start gap-1">
          <DiscountBadge pct={product.discount_pct} />
          {product.badges.includes('new') ? (
            <span className="rounded-md bg-sky-600 px-1.5 py-0.5 text-xs font-semibold text-white">
              NEW
            </span>
          ) : null}
          {product.badges.includes('price_drop') && product.prev_price !== null ? (
            <span
              title={`was ${formatPrice(product.prev_price)}`}
              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-1.5 py-0.5 text-xs font-semibold text-white"
            >
              <TrendingDownIcon className="size-3" /> cheaper
            </span>
          ) : null}
          {!product.is_active ? (
            <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-xs text-white">
              Not in sale
            </span>
          ) : null}
        </span>
      </button>
      <FavoriteButton
        id={product.id}
        active={product.is_favorite}
        className="absolute top-2 right-2"
      />

      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="flex items-start justify-between gap-2">
          <p className="truncate text-sm font-semibold">{product.brand.name}</p>
          <a
            href={product.url}
            target="_blank"
            rel="noreferrer"
            aria-label="Open on the shop site"
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <ExternalLinkIcon className="size-4" />
          </a>
        </div>
        {site.show ? (
          <p className="-mt-1 text-[11px] tracking-wide text-muted-foreground uppercase">
            {site.name}
          </p>
        ) : null}
        <p className="line-clamp-2 text-sm text-muted-foreground">{product.name}</p>
        {shown.length ? (
          <ul className="flex flex-wrap gap-1" aria-label="Sizes in stock">
            {shown.map((s) => (
              <li
                key={s.label}
                className={cn(
                  'rounded border px-1.5 text-xs',
                  s.is_mine && 'border-primary bg-primary text-primary-foreground',
                )}
              >
                {s.label}
              </li>
            ))}
            {inStock.length > shown.length ? (
              <li className="px-1 text-xs text-muted-foreground">
                +{inStock.length - shown.length}
              </li>
            ) : null}
          </ul>
        ) : null}
        <div className="mt-auto flex flex-wrap items-baseline gap-x-2 pt-1">
          <span className="text-base font-semibold">{formatPrice(product.price)}</span>
          <span className="text-xs text-muted-foreground line-through">
            {formatPrice(product.price_regular)}
          </span>
          <span className="text-xs text-emerald-700 dark:text-emerald-400">
            -{formatPrice(product.savings)}
          </span>
        </div>
        {footer}
      </div>
    </article>
  )
}
