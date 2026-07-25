import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/lib/auth-context'
import { useAuth } from '@/lib/auth-types'

const mocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  headers: {} as Record<string, string>,
}))

vi.mock('@/api', () => ({
  api: { defaults: { headers: { common: mocks.headers } } },
  getMe: mocks.getMe,
  setUnauthorizedHandler: mocks.setUnauthorizedHandler,
}))

function AuthState() {
  const { user, isAuthenticated, isInitializing } = useAuth()
  return (
    <div>
      <span>{isInitializing ? 'initializing' : 'ready'}</span>
      <span>{isAuthenticated ? user?.name : 'signed-out'}</span>
    </div>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.getMe.mockReset()
    mocks.setUnauthorizedHandler.mockReset()
    for (const key of Object.keys(mocks.headers)) delete mocks.headers[key]
  })

  it('waits for initial identity before enabling global 401 logout', async () => {
    localStorage.setItem('token', 'stored-token')
    let resolveMe!: (value: { data: { id: string; email: string; name: string; role: string } }) => void
    mocks.getMe.mockReturnValue(new Promise((resolve) => {
      resolveMe = resolve
    }))

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(screen.getByText('initializing')).toBeInTheDocument()
    expect(mocks.setUnauthorizedHandler).not.toHaveBeenCalled()

    await act(async () => {
      resolveMe({
        data: { id: 'user-1', email: 'ada@example.com', name: 'Ada', role: 'USER' },
      })
    })

    expect(await screen.findByText('ready')).toBeInTheDocument()
    expect(screen.getByText('Ada')).toBeInTheDocument()
    await waitFor(() => expect(mocks.setUnauthorizedHandler).toHaveBeenCalled())

    const handler = mocks.setUnauthorizedHandler.mock.calls.find(([value]) => typeof value === 'function')?.[0]
    expect(handler).toBeTypeOf('function')
    act(() => handler())
    expect(screen.getByText('signed-out')).toBeInTheDocument()
    expect(localStorage.getItem('token')).toBeNull()
  })
})
