import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { facetsQuery, settingsQuery, useUpdateMySizes } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCount } from '@/lib/format'
import { groupSizes, type SizeGroup } from '@/lib/sizes'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/settings')({ component: SettingsPage })

const GROUP_LABELS: Record<SizeGroup, string> = {
  letters: 'Clothing',
  numbers: 'Numeric (shoes, jeans...)',
  other: 'Other',
}

function SettingsPage() {
  const settings = useQuery(settingsQuery)
  const facets = useQuery(facetsQuery({}))
  const update = useUpdateMySizes()
  const [filter, setFilter] = useState('')

  const mine = useMemo(() => new Set(settings.data?.my_sizes ?? []), [settings.data])
  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const known = facets.data?.sizes ?? []
    const extra = [...mine]
      .filter((label) => !known.some((s) => s.label === label))
      .map((label) => ({ label, count: 0 }))
    return groupSizes(
      [...known, ...extra].filter((s) => !needle || s.label.toLowerCase().includes(needle)),
    )
  }, [facets.data, mine, filter])

  const toggle = (label: string) => {
    const next = mine.has(label) ? [...mine].filter((s) => s !== label) : [...mine, label]
    update.mutate(next, { onError: (e) => toast.error(e.message) })
  }

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>
      <section className="space-y-3 rounded-xl border p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <h2 className="font-semibold">My sizes</h2>
            <p className="text-sm text-muted-foreground">
              "Only my sizes" in the catalog shows items where at least one of these is in stock;
              they are also highlighted on every card.
            </p>
          </div>
          {mine.size ? (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={() => update.mutate([], { onError: (e) => toast.error(e.message) })}
            >
              Clear all
            </Button>
          ) : null}
        </div>
        <p className="text-sm">
          Selected:{' '}
          {mine.size ? <span className="font-medium">{[...mine].join(', ')}</span> : 'none'}
        </p>
        <Input
          placeholder="Find a size"
          value={filter}
          onChange={(e) => setFilter(e.currentTarget.value)}
          aria-label="Find a size"
          className="max-w-60"
        />
        {settings.isPending || facets.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          (['letters', 'numbers', 'other'] as const).map((group) =>
            groups[group].length ? (
              <div key={group} className="space-y-1.5">
                <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {GROUP_LABELS[group]}
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {groups[group].map((s) => (
                    <button
                      key={s.label}
                      type="button"
                      aria-pressed={mine.has(s.label)}
                      onClick={() => toggle(s.label)}
                      title={`${formatCount(s.count)} items in stock now`}
                      className={cn(
                        'rounded-md border px-2.5 py-1 text-sm transition hover:border-foreground/40',
                        mine.has(s.label) && 'border-primary bg-primary text-primary-foreground',
                      )}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null,
          )
        )}
      </section>
    </div>
  )
}
