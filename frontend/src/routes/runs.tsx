import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { runsQuery, sitesQuery } from '@/api/queries'
import type { RunOut } from '@/api/types'
import { RefreshMenu, STATUS_DOT } from '@/components/runs/run-controls'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatCount, formatDateTime, formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/runs')({ component: RunsPage })

function stat(run: RunOut, key: string): string {
  const value = run.stats?.[key]
  return typeof value === 'number' ? formatCount(value) : '-'
}

function RunsPage() {
  const { data: runs, isPending } = useQuery(runsQuery(50))
  const { data: sites } = useQuery(sitesQuery)
  const names = new Map((sites ?? []).map((s) => [s.code, s.name]))

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Scrape runs</h1>
        <div className="ml-auto">
          {sites ? <RefreshMenu sites={sites} label="Run now" /> : null}
        </div>
      </div>
      {isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead>Shop</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead className="text-right">Items</TableHead>
                <TableHead className="text-right">New</TableHead>
                <TableHead className="text-right">Cheaper</TableHead>
                <TableHead className="text-right">Removed</TableHead>
                <TableHead>Note</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs ?? []).map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="text-muted-foreground tabular-nums">{run.id}</TableCell>
                  <TableCell>{names.get(run.site) ?? run.site}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5">
                      <span className={cn('size-2 rounded-full', STATUS_DOT[run.status])} />
                      {run.status}
                      <span className="text-xs text-muted-foreground">({run.trigger})</span>
                    </span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatDateTime(run.started_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {run.status === 'running'
                      ? `${run.pages_done}/${run.pages_total ?? '?'} pages`
                      : formatDuration(run.started_at, run.finished_at)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCount(run.items_seen)}
                    {run.expected_total ? (
                      <span className="text-muted-foreground">
                        {' '}
                        / {formatCount(run.expected_total)}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{stat(run, 'new')}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {stat(run, 'price_drops')}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{stat(run, 'removed')}</TableCell>
                  <TableCell
                    className="max-w-72 truncate text-muted-foreground"
                    title={run.error ?? undefined}
                  >
                    {run.error ?? (run.status === 'partial' ? 'incomplete: nothing removed' : '')}
                  </TableCell>
                </TableRow>
              ))}
              {runs?.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={10} className="py-10 text-center text-muted-foreground">
                    No runs yet.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
