export type AccentId = 'sky' | 'violet' | 'emerald' | 'amber' | 'red'

export const ACCENT_STORAGE_KEY = 'app-accent'

export interface AccentTokensHsl {
  primary: string
  primaryForeground: string
  accent: string
  accentForeground: string
  ring: string
}

export interface AccentPreset {
  id: AccentId
  label: string
  swatch: string
  light: AccentTokensHsl
  dark: AccentTokensHsl
}

/** HSL values without hsl() wrapper — matches shadcn index.css format */
export const ACCENT_PRESETS: AccentPreset[] = [
  {
    id: 'sky',
    label: 'Sky',
    swatch: '#38bdf8',
    light: {
      primary: '199 89% 48%',
      primaryForeground: '210 40% 98%',
      accent: '199 80% 55%',
      accentForeground: '222.2 47.4% 11.2%',
      ring: '199 89% 48%',
    },
    dark: {
      primary: '199 89% 55%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '199 70% 45%',
      accentForeground: '210 40% 98%',
      ring: '199 89% 55%',
    },
  },
  {
    id: 'violet',
    label: 'Violet',
    swatch: '#8b5cf6',
    light: {
      primary: '262 83% 58%',
      primaryForeground: '210 40% 98%',
      accent: '262 70% 65%',
      accentForeground: '222.2 47.4% 11.2%',
      ring: '262 83% 58%',
    },
    dark: {
      primary: '262 83% 65%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '262 60% 50%',
      accentForeground: '210 40% 98%',
      ring: '262 83% 65%',
    },
  },
  {
    id: 'emerald',
    label: 'Emerald',
    swatch: '#10b981',
    light: {
      primary: '160 84% 39%',
      primaryForeground: '210 40% 98%',
      accent: '160 70% 45%',
      accentForeground: '222.2 47.4% 11.2%',
      ring: '160 84% 39%',
    },
    dark: {
      primary: '160 84% 45%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '160 60% 35%',
      accentForeground: '210 40% 98%',
      ring: '160 84% 45%',
    },
  },
  {
    id: 'amber',
    label: 'Amber',
    swatch: '#f59e0b',
    light: {
      primary: '38 92% 50%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '38 85% 55%',
      accentForeground: '222.2 47.4% 11.2%',
      ring: '38 92% 50%',
    },
    dark: {
      primary: '38 92% 55%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '38 70% 40%',
      accentForeground: '210 40% 98%',
      ring: '38 92% 55%',
    },
  },
  {
    id: 'red',
    label: 'Red',
    swatch: '#ef4444',
    light: {
      primary: '0 84% 60%',
      primaryForeground: '210 40% 98%',
      accent: '0 75% 65%',
      accentForeground: '222.2 47.4% 11.2%',
      ring: '0 84% 60%',
    },
    dark: {
      primary: '0 84% 58%',
      primaryForeground: '222.2 47.4% 11.2%',
      accent: '0 65% 45%',
      accentForeground: '210 40% 98%',
      ring: '0 84% 58%',
    },
  },
]

export const DEFAULT_ACCENT_ID: AccentId = 'sky'

export function loadAccentId(): AccentId {
  try {
    const stored = localStorage.getItem(ACCENT_STORAGE_KEY) as AccentId | null
    if (stored && ACCENT_PRESETS.some((p) => p.id === stored)) {
      return stored
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_ACCENT_ID
}

export function saveAccentId(id: AccentId): void {
  try {
    localStorage.setItem(ACCENT_STORAGE_KEY, id)
  } catch {
    /* ignore */
  }
}

export function applyAccentTokens(id: AccentId, mode: 'light' | 'dark'): void {
  const preset = ACCENT_PRESETS.find((p) => p.id === id) ?? ACCENT_PRESETS[0]
  const tokens = mode === 'dark' ? preset.dark : preset.light
  const root = document.documentElement

  root.style.setProperty('--primary', tokens.primary)
  root.style.setProperty('--primary-foreground', tokens.primaryForeground)
  root.style.setProperty('--accent', tokens.accent)
  root.style.setProperty('--accent-foreground', tokens.accentForeground)
  root.style.setProperty('--ring', tokens.ring)
  root.style.setProperty('--chat-user-bg', `hsl(${tokens.primary})`)
  root.dataset.accent = id
}
