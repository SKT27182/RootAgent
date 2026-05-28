import { useState, useEffect } from 'react'
import { Settings, User, Palette, Key, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useTheme } from '@/components/theme-provider'
import { ThemeToggle } from '@/components/ThemeToggle'
import { AccentPicker } from '@/components/AccentPicker'
import { useAuth } from '@/lib/auth-context'
import { updateProfile, changePassword } from '@/api'
import { userDisplayName, userInitial } from '@/lib/display'
import { SettingsShell } from '@/components/layout/SettingsShell'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { cn } from '@/lib/utils'

export default function SettingsPage() {
  useDocumentTitle('Settings — RootAgent')
  const { user, logout, loadUser } = useAuth()
  const { theme, setTheme } = useTheme()
  const [activeTab, setActiveTab] = useState<'profile' | 'appearance'>('profile')

  const [name, setName] = useState(user?.name ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [profileError, setProfileError] = useState('')
  const [profileSuccess, setProfileSuccess] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)

  useEffect(() => {
    setName(user?.name ?? '')
  }, [user?.name])

  const tabs = [
    { id: 'profile' as const, label: 'Profile', icon: User },
    { id: 'appearance' as const, label: 'Appearance', icon: Palette },
  ]

  const handleSaveProfile = async () => {
    setProfileError('')
    setProfileSuccess('')
    if (!name.trim()) {
      setProfileError('Name is required')
      return
    }
    setSavingProfile(true)
    try {
      await updateProfile(name.trim())
      await loadUser()
      setProfileSuccess('Profile updated')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail
          : undefined
      setProfileError(typeof detail === 'string' ? detail : 'Failed to update profile')
    } finally {
      setSavingProfile(false)
    }
  }

  const handleChangePassword = async () => {
    setPasswordError('')
    setPasswordSuccess('')
    if (newPassword !== confirmPassword) {
      setPasswordError('Passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      setPasswordError('Password must be at least 8 characters')
      return
    }
    setSavingPassword(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordSuccess('Password updated')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail
          : undefined
      setPasswordError(typeof detail === 'string' ? detail : 'Failed to update password')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <SettingsShell>
      <div className="space-y-8 animate-fade-in">
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-primary/10">
            <Settings className="h-6 w-6 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
            <p className="text-muted-foreground">
              Manage your account and preferences
            </p>
          </div>
        </div>

        <div className="flex flex-col md:flex-row gap-6 md:gap-8">
          <nav className="w-full md:w-48 space-y-1 flex md:flex-col flex-row flex-wrap gap-1">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  activeTab === id
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted'
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </nav>

          <div className="flex-1 space-y-6">
            {activeTab === 'profile' && (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>Profile Information</CardTitle>
                    <CardDescription>Update your account details</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center gap-4 mb-2">
                      <div className="h-16 w-16 rounded-full bg-primary/20 flex items-center justify-center text-2xl font-bold text-primary">
                        {userInitial(user)}
                      </div>
                      <div>
                        <p className="font-medium">{userDisplayName(user)}</p>
                        <p className="text-sm text-muted-foreground capitalize">
                          {user?.role?.toLowerCase()} account
                        </p>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label htmlFor="profile-email" className="text-sm font-medium">
                        Email
                      </label>
                      <Input
                        id="profile-email"
                        type="email"
                        value={user?.email || ''}
                        disabled
                      />
                      <p className="text-xs text-muted-foreground">
                        Email cannot be changed
                      </p>
                    </div>

                    <div className="space-y-2">
                      <label htmlFor="profile-name" className="text-sm font-medium">
                        Display name
                      </label>
                      <Input
                        id="profile-name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </div>

                    {profileError && (
                      <p className="text-sm text-destructive">{profileError}</p>
                    )}
                    {profileSuccess && (
                      <p className="text-sm text-primary">{profileSuccess}</p>
                    )}

                    <Button onClick={handleSaveProfile} disabled={savingProfile}>
                      <Save className="h-4 w-4 mr-2" />
                      {savingProfile ? 'Saving...' : 'Save profile'}
                    </Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Key className="h-5 w-5" />
                      Change Password
                    </CardTitle>
                    <CardDescription>Update your account password</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Current password</label>
                      <Input
                        type="password"
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        autoComplete="current-password"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">New password</label>
                      <Input
                        type="password"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        autoComplete="new-password"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Confirm new password</label>
                      <Input
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        autoComplete="new-password"
                      />
                    </div>
                    {passwordError && (
                      <p className="text-sm text-destructive">{passwordError}</p>
                    )}
                    {passwordSuccess && (
                      <p className="text-sm text-primary">{passwordSuccess}</p>
                    )}
                    <Button onClick={handleChangePassword} disabled={savingPassword}>
                      <Save className="h-4 w-4 mr-2" />
                      {savingPassword ? 'Updating...' : 'Update password'}
                    </Button>
                  </CardContent>
                </Card>

                <Card className="border-destructive/50">
                  <CardHeader>
                    <CardTitle className="text-destructive">Danger Zone</CardTitle>
                    <CardDescription>Irreversible actions</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Button variant="destructive" onClick={logout}>
                      Sign out
                    </Button>
                  </CardContent>
                </Card>
              </>
            )}

            {activeTab === 'appearance' && (
              <Card>
                <CardHeader>
                  <CardTitle>Appearance</CardTitle>
                  <CardDescription>Customize how RootAgent looks</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-3">
                    <label className="text-sm font-medium">Theme</label>
                    <div className="flex flex-wrap items-center gap-3">
                      {(['light', 'dark'] as const).map((mode) => (
                        <Button
                          key={mode}
                          type="button"
                          variant={theme === mode ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => setTheme(mode)}
                          className="capitalize"
                        >
                          {mode}
                        </Button>
                      ))}
                      <ThemeToggle />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium">Accent color</label>
                    <AccentPicker />
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </SettingsShell>
  )
}
