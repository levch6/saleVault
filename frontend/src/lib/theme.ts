/** Keep the `dark` class on <html> in sync with the OS color scheme. */
export function followSystemTheme(): void {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const apply = () => document.documentElement.classList.toggle('dark', media.matches)
  apply()
  media.addEventListener('change', apply)
}
