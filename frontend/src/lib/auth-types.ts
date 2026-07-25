import { createContext, useContext } from 'react'
import type { AuthUser } from '@/api'

export interface AuthContextType {
  user: AuthUser | null
  token: string | null
  login: (token: string, user?: AuthUser | null) => void
  logout: () => void
  loadUser: () => Promise<void>
  isAuthenticated: boolean
  isInitializing: boolean
}

export const AuthContext = createContext<AuthContextType | null>(null)

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
