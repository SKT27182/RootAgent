import { api } from '../api'
import type { AuthUser } from '../api'

export const adminApi = {
  listUsers: async (): Promise<AuthUser[]> => {
    const { data } = await api.get<AuthUser[]>('/admin/users')
    return data
  },

  createUser: async (payload: {
    email: string
    password: string
    role: string
  }): Promise<AuthUser> => {
    const { data } = await api.post<AuthUser>('/admin/users', payload)
    return data
  },

  updateUserRole: async (userId: string, role: string): Promise<AuthUser> => {
    const { data } = await api.patch<AuthUser>(
      `/admin/users/${userId}/role?role=${role}`
    )
    return data
  },

  deleteUser: async (userId: string): Promise<void> => {
    await api.delete(`/admin/users/${userId}`)
  },
}
