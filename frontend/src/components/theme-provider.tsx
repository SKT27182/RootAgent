import { useEffect, useState } from 'react'
import { applyAccentTokens, loadAccentId } from '@/lib/accent-presets'
import { ThemeProviderContext, type Theme } from '@/lib/theme-context'

export function ThemeProvider({
  children,
  defaultTheme = 'dark',
  storageKey = 'rootagent-theme',
}: {
  children: React.ReactNode
  defaultTheme?: Theme
  storageKey?: string
}) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(storageKey) as Theme) || defaultTheme
  )

  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(theme)
    applyAccentTokens(loadAccentId(), theme)
  }, [theme])

  return (
    <ThemeProviderContext.Provider
      value={{
        theme,
        setTheme: (next: Theme) => {
          localStorage.setItem(storageKey, next)
          setTheme(next)
        },
      }}
    >
      {children}
    </ThemeProviderContext.Provider>
  )
}
