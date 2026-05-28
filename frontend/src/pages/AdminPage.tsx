import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Shield, Plus, Trash2, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { adminApi } from '@/lib/admin-api'
import type { AuthUser } from '@/api'
import { useAuth } from '@/lib/auth-context'
import {
  canCreateAdmin,
  canDeleteUser,
  canManageRoles,
  hasAdminAccess,
} from '@/lib/roles'
import { Navigate } from 'react-router-dom'
export default function AdminPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<AuthUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [newRole, setNewRole] = useState<'USER' | 'ADMIN'>('USER')
  const [saving, setSaving] = useState(false)

  if (!hasAdminAccess(currentUser?.role)) {
    return <Navigate to="/" replace />
  }

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setUsers(await adminApi.listUsers())
    } catch (e: unknown) {
      const msg =
        e && typeof e === 'object' && 'response' in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(msg || (e instanceof Error ? e.message : 'Failed to load users'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await adminApi.createUser({ email, password, role: newRole })
      setEmail('')
      setPassword('')
      setShowCreate(false)
      await load()
    } catch (e: unknown) {
      const msg =
        e && typeof e === 'object' && 'response' in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(msg || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  const handleRoleChange = async (userId: string, role: string) => {
    try {
      await adminApi.updateUserRole(userId, role)
      await load()
    } catch (e: unknown) {
      const msg =
        e && typeof e === 'object' && 'response' in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(msg || 'Role update failed')
    }
  }

  const handleDelete = async (u: AuthUser) => {
    if (!confirm(`Delete user "${u.email}"?`)) return
    try {
      await adminApi.deleteUser(u.id)
      await load()
    } catch (e: unknown) {
      const msg =
        e && typeof e === 'object' && 'response' in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(msg || 'Delete failed')
    }
  }

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="h-8 w-8 text-primary" />
            <div>
              <h1 className="text-2xl font-bold">Admin</h1>
              <p className="text-sm text-muted-foreground">User management</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" asChild>
              <Link to="/">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to chat
              </Link>
            </Button>
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add user
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {showCreate && (
          <Card>
            <CardHeader>
              <CardTitle>Create user</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCreate} className="grid gap-4 max-w-md">
                <Input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
                <Input
                  type="password"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as 'USER' | 'ADMIN')}
                >
                  <option value="USER">User</option>
                  {canCreateAdmin(currentUser?.role) && (
                    <option value="ADMIN">Administrator</option>
                  )}
                </select>
                <div className="flex gap-2">
                  <Button type="submit" disabled={saving}>
                    {saving ? 'Creating…' : 'Create'}
                  </Button>
                  <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="p-0">
            {loading ? (
              <p className="p-6 text-muted-foreground">Loading…</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="p-4">Email</th>
                    <th className="p-4">Role</th>
                    <th className="p-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const isTargetInfra = u.role === 'INFRA_ADMIN'
                    const canEditRole = canManageRoles(currentUser?.role) && !isTargetInfra
                    const canDel = canDeleteUser(currentUser?.role, u.role) && u.id !== currentUser?.id
                    return (
                      <tr key={u.id} className="border-b last:border-0">
                        <td className="p-4">{u.email}</td>
                        <td className="p-4">
                          {canEditRole ? (
                            <select
                              className="rounded border border-input bg-transparent px-2 py-1 text-sm"
                              value={u.role}
                              onChange={(e) => handleRoleChange(u.id, e.target.value)}
                            >
                              <option value="USER">User</option>
                              <option value="ADMIN">Admin</option>
                            </select>
                          ) : (
                            <span className="rounded bg-muted px-2 py-0.5 text-xs">
                              {isTargetInfra ? 'Infra Admin' : u.role}
                            </span>
                          )}
                        </td>
                        <td className="p-4 text-right">
                          {canDel && (
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDelete(u)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
