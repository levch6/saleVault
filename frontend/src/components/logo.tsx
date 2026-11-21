/** The app mark: the same drawing as `public/favicon.svg`, colored by the current theme. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="7" className="fill-foreground" />
      <g className="fill-background stroke-background">
        <circle cx="10.25" cy="10.25" r="3.75" stroke="none" />
        <circle cx="21.75" cy="21.75" r="3.75" stroke="none" />
        <path d="M22.75 8.25 9.25 23.75" fill="none" strokeWidth="3.5" strokeLinecap="round" />
      </g>
    </svg>
  )
}
