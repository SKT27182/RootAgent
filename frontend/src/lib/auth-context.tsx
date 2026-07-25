import React, { useCallback, useEffect, useState } from 'react'
import { api, getMe, setUnauthorizedHandler, type AuthUser } from '@/api'
import { AuthContext } from '@/lib/auth-types'

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [isInitializing, setIsInitializing] = useState(() => Boolean(localStorage.getItem('token')))

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    delete api.defaults.headers.common.Authorization
    setToken(null)
    setUser(null)
  }, [])

  const login = (newToken: string, newUser: AuthUser | null = null) => {
    localStorage.setItem('token', newToken)
    api.defaults.headers.common.Authorization = `Bearer ${newToken}`
    setToken(newToken)
    if (newUser) {
      setUser(newUser)
    }
  }

  useEffect(() => {
    const storedToken = localStorage.getItem('token')
    if (!storedToken) {
      return
    }

    api.defaults.headers.common.Authorization = `Bearer ${storedToken}`
    let active = true
    void getMe()
      .then((response) => {
        if (active) setUser(response.data)
      })
      .catch(() => {
        if (active) logout()
      })
      .finally(() => {
        if (active) setIsInitializing(false)
      })

    return () => {
      active = false
    }
  }, [logout])

  useEffect(() => {
    if (isInitializing) return
    setUnauthorizedHandler(() => {
      if (localStorage.getItem('token')) logout()
    })
    return () => setUnauthorizedHandler(null)
  }, [isInitializing, logout])

  const loadUser = async () => {
    const res = await getMe()
    setUser(res.data)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        login,
        logout,
        loadUser,
        isAuthenticated: Boolean(token && user),
        isInitializing,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
