import { useQuery } from '@tanstack/react-query'
import { healthQuery } from '@/api/queries'
import { cn } from '@/lib/utils'

/** Small header indicator: is the backend reachable, and which version is it. */
export function HealthStatus() {
  const { data, isPending, isError } = useQuery(healthQuery)

  let label = 'Checking API...'
  let dot = 'animate-pulse bg-muted-foreground/40'
  if (isError) {
    label = 'API offline'
    dot = 'bg-destructive'
  } else if (!isPending) {
    label = `API online, v${data.version}`
    dot = 'bg-emerald-500'
  }

  return (
    <output className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <span aria-hidden="true" className={cn('size-2 rounded-full', dot)} />
      {label}
    </output>
  )
}
