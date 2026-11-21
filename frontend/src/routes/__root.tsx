import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router'
import { HealthStatus } from '@/components/health-status'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFound,
})

function RootLayout() {
  return (
    <div className="min-h-svh">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-screen-2xl items-center gap-6 px-4">
          <Link to="/" className="font-heading text-lg font-semibold tracking-tight">
            saleVault
          </Link>
          <div className="ml-auto">
            <HealthStatus />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-screen-2xl px-4 py-6">
        <Outlet />
      </main>
    </div>
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
