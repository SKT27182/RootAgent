import type { ReactNode } from 'react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { AppSidebar } from './AppSidebar'
import { useAuth } from '@/lib/auth-context'
import { userDisplayName, userInitial } from '@/lib/display'

interface SettingsShellProps {
  children: ReactNode
}

export function SettingsShell({ children }: SettingsShellProps) {
  const { user, logout } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex h-[100dvh] w-full bg-background text-foreground overflow-hidden relative">
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <AppSidebar
        variant="settings"
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 transition-transform duration-300 ease-in-out md:relative md:translate-x-0 md:flex shrink-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        )}
        sessions={[]}
        currentSessionId={null}
        displayName={userDisplayName(user)}
        userInitial={userInitial(user)}
        userRole={user?.role}
        onSelectSession={() => {}}
        onCreateSession={() => {}}
        onDeleteSession={() => {}}
        onCopySessionId={() => {}}
        onLogout={logout}
        onClose={() => setSidebarOpen(false)}
        showCloseButton
      />

      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="md:hidden border-b px-4 h-14 flex items-center">
          <button
            type="button"
            className="text-sm font-medium text-muted-foreground"
            onClick={() => setSidebarOpen(true)}
          >
            Menu
          </button>
        </div>
        <div className="p-6 md:p-8 max-w-4xl mx-auto">{children}</div>
      </main>
    </div>
  )
}
