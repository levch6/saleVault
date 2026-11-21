import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCwIcon, XIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import {
  invalidateCatalog,
  runningSites,
  sitesQuery,
  useCancelRun,
  useStartRun,
} from '@/api/queries'
import type { RunOut, SiteOut } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatCount, formatDateTime, formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

export const STATUS_DOT: Record<RunOut['status'], string> = {
  success: 'bg-emerald-500',
  partial: 'bg-amber-500',
  failed: 'bg-red-500',
  cancelled: 'bg-zinc-400',
  running: 'bg-sky-500 animate-pulse',
}

function stat(run: RunOut, key: string): number {
  const value = run.stats?.[key]
  return typeof value === 'number' ? value : 0
}

export function runSummary(site: string, run: RunOut): string {
  return `${site}: ${formatCount(stat(run, 'seen'))} items, ${stat(run, 'new')} new, ${stat(run, 'price_drops')} cheaper, ${stat(run, 'removed')} removed`
}

/** Toasts when a run ends, then reloads everything that depends on the data. */
function useRunNotifications(sites: readonly SiteOut[] | undefined) {
  const client = useQueryClient()
  const running = useRef(new Map<string, number>())
  useEffect(() => {
    for (const site of sites ?? []) {
      const latest = site.latest
      if (latest?.status === 'running') {
        running.current.set(site.code, latest.id)
        continue
      }
      const watched = running.current.get(site.code)
      if (watched === undefined) continue
      running.current.delete(site.code)
      invalidateCatalog(client)
      if (!latest || latest.id !== watched) continue
      if (latest.status === 'success') toast.success(`${runSummary(site.name, latest)}.`)
      else if (latest.status === 'partial')
        toast.warning(`${runSummary(site.name, latest)}. Partial run: nothing was removed.`)
      else if (latest.status === 'cancelled')
        toast.info(
          `${site.name}: run cancelled. Continue it with "just scrape ${site.code} --resume".`,
        )
      else toast.error(`${site.name}: run failed. ${latest.error ?? ''}`)
    }
  }, [sites, client])
}

function SiteChip({ site }: { site: SiteOut }) {
  const shown = site.last_completed
  const latest = site.latest
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs">
          <span
            className={cn(
              'size-2 rounded-full',
              latest ? STATUS_DOT[latest.status] : 'bg-zinc-300',
            )}
          />
          <span className="font-medium">{site.name}</span>
          <span className="hidden text-muted-foreground 2xl:inline">
            {shown?.finished_at ? formatDateTime(shown.finished_at) : 'never scraped'}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72 space-y-1">
        <p>{formatCount(site.active_products)} items in the catalog</p>
        {shown ? (
          <p>
            Last update {shown.finished_at ? formatDateTime(shown.finished_at) : '-'} (
            {formatDuration(shown.started_at, shown.finished_at)}): {stat(shown, 'new')} new,{' '}
            {stat(shown, 'price_drops')} cheaper, {stat(shown, 'removed')} removed
          </p>
        ) : null}
        {latest && latest.id !== shown?.id && latest.status !== 'running' ? (
          <p>
            Latest run #{latest.id} {latest.status}
            {latest.error ? `: ${latest.error}` : ''}
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  )
}

function RunProgress({ site }: { site: SiteOut }) {
  const run = site.latest
  const cancel = useCancelRun()
  if (!run) return null
  const total = run.pages_total ?? 0
  const value = total ? (run.pages_done / total) * 100 : 0
  return (
    <div className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs">
      <RefreshCwIcon className="size-3.5 animate-spin text-sky-600" />
      <span className="font-medium">{site.name}</span>
      <Progress
        value={value}
        className="hidden w-24 sm:block"
        aria-label={`${site.name} progress`}
      />
      <span className="text-muted-foreground tabular-nums">
        {total ? `${run.pages_done}/${total} pages` : 'planning'}, {formatCount(run.items_seen)}{' '}
        items
      </span>
      <button
        type="button"
        aria-label={`Cancel ${site.name} run`}
        disabled={cancel.isPending}
        onClick={() => cancel.mutate(run.id, { onError: (e) => toast.error(e.message) })}
        className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <XIcon className="size-3.5" />
      </button>
    </div>
  )
}

export function RefreshMenu({
  sites,
  label = 'Refresh',
}: {
  sites: readonly SiteOut[]
  label?: string
}) {
  const start = useStartRun()
  const run = (code: string, resume = false) =>
    start.mutate(
      { site: code, resume },
      {
        onSuccess: (result) => {
          toast.info(
            `${resume ? 'Resuming the run' : 'Scraping started'}. A browser window may appear for a moment.`,
          )
          for (const reason of result.skipped ?? []) toast.warning(reason)
        },
        onError: (e) => toast.error(e.message),
      },
    )
  // A cancelled or failed run keeps its fetched pages: offer to go on instead of starting over.
  const resumable = sites.filter((s) => s.resumable && s.latest)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" disabled={start.isPending}>
          <RefreshCwIcon className={cn(start.isPending && 'animate-spin')} /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {resumable.length ? (
          <>
            <DropdownMenuLabel>Continue where it stopped</DropdownMenuLabel>
            {resumable.map((s) => (
              <DropdownMenuItem key={`resume-${s.code}`} onSelect={() => run(s.code, true)}>
                Resume {s.name}
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                  {s.latest?.pages_done}/{s.latest?.pages_total ?? '?'} pages
                </span>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuLabel>Scrape the sale now</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {sites.length > 1 ? (
          <DropdownMenuItem onSelect={() => run('all')}>All shops</DropdownMenuItem>
        ) : null}
        {sites.map((s) => (
          <DropdownMenuItem key={s.code} onSelect={() => run(s.code)}>
            {s.name}
            <span className="ml-auto text-xs text-muted-foreground">
              {s.resumable
                ? 'starts over'
                : s.last_completed
                  ? `last ${formatDuration(s.last_completed.started_at, s.last_completed.finished_at)}`
                  : ''}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function RunControls() {
  const { data: sites } = useQuery(sitesQuery)
  useRunNotifications(sites)
  if (!sites) return null
  const running = runningSites(sites)
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {sites
        .filter((s) => s.latest?.status !== 'running')
        .map((s) => (
          <SiteChip key={s.code} site={s} />
        ))}
      {running.map((s) => (
        <RunProgress key={s.code} site={s} />
      ))}
      {running.length < sites.length ? (
        <RefreshMenu sites={sites.filter((s) => s.latest?.status !== 'running')} />
      ) : null}
    </div>
  )
}
