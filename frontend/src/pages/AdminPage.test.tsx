import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminPage from '@/pages/AdminPage'

const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
}))

vi.mock('@/lib/auth-types', () => ({
  useAuth: () => ({
    user: { id: 'admin-1', email: 'admin@example.com', name: 'Admin', role: 'ADMIN' },
  }),
}))

vi.mock('@/lib/admin-api', () => ({
  adminApi: {
    listUsers: mocks.listUsers,
    createUser: mocks.createUser,
    updateUserRole: vi.fn(),
    deleteUser: vi.fn(),
  },
}))

describe('AdminPage', () => {
  beforeEach(() => {
    mocks.listUsers.mockResolvedValue([])
    mocks.createUser.mockResolvedValue({})
  })

  it('requires and persists a new user name', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><AdminPage /></MemoryRouter>)

    await screen.findByText('User management')
    await user.click(screen.getByRole('button', { name: /add user/i }))
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Ada Lovelace')
    await user.type(screen.getByPlaceholderText('Email'), 'ada@example.com')
    await user.type(screen.getByPlaceholderText('Password'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(mocks.createUser).toHaveBeenCalledWith({
        name: 'Ada Lovelace',
        email: 'ada@example.com',
        password: 'correct-horse',
        role: 'USER',
      })
    })
  })
})
