import createClient from 'openapi-fetch'
import type { paths } from './schema'

/**
 * Typed client for the saleVault API; types are generated from FastAPI (`just gen-api`).
 * `fetch` is resolved lazily so tests can stub `globalThis.fetch`.
 */
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})
