import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: CatalogPage,
})

function CatalogPage() {
  return (
    <section className="flex flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-2xl font-semibold">No data yet</h1>
      <p className="max-w-md text-muted-foreground">
        The catalog will appear here after the first scrape.
      </p>
    </section>
  )
}
