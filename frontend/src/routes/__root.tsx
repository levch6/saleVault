import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  type ErrorComponentProps,
  Link,
  Outlet,
} from '@tanstack/react-router'
import { HealthStatus } from '@/components/health-status'
import { Logo } from '@/components/logo'
import { RunControls } from '@/components/runs/run-controls'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFound,
  errorComponent: RenderError,
})

const NAV = [
  { to: '/', label: 'Catalog' },
  { to: '/favorites', label: 'Favorites' },
  { to: '/runs', label: 'Runs' },
  { to: '/settings', label: 'Settings' },
] as const

function RootLayout() {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="min-h-svh">
        <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
            <Link
              to="/"
              className="flex items-center gap-2 font-heading text-lg font-semibold tracking-tight"
            >
              <Logo className="size-6 shrink-0" />
              saleVault
            </Link>
            <nav className="flex gap-1 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  activeOptions={{ exact: item.to === '/', includeSearch: false }}
                  className="rounded-md px-2.5 py-1.5 text-muted-foreground transition hover:text-foreground"
                  activeProps={{ className: 'bg-muted text-foreground font-medium' }}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-3">
              <RunControls />
              <HealthStatus compact />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-screen-2xl px-4 py-5">
          <Outlet />
        </main>
        <Toaster position="bottom-right" richColors closeButton />
      </div>
    </TooltipProvider>
  )
}

function NotFound() {
  return (
    <section className="flex flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="text-primary underline-offset-4 hover:underline">
        Back to the catalog
      </Link>
    </section>
  )
}

/** A render error shows this instead of a blank page; the header stays usable. */
function RenderError({ error, reset }: ErrorComponentProps) {
  return (
    <section role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        {error instanceof Error ? error.message : String(error)}
      </p>
      <button
        type="button"
        onClick={reset}
        className="text-primary underline-offset-4 hover:underline"
      >
        Try again
      </button>
    </section>
  )
}
