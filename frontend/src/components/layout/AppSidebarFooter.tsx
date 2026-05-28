import { Link } from 'react-router-dom'
import { Settings, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ThemeToggle } from '@/components/ThemeToggle'

interface AppSidebarFooterProps {
  collapsed?: boolean
  displayName?: string
  userInitial?: string
  role?: string
  onLogout: () => void
  onNavigate?: () => void
  settingsHref?: string
}

export function AppSidebarFooter({
  collapsed = false,
  displayName = 'User',
  userInitial: initial = '?',
  role,
  onLogout,
  onNavigate,
  settingsHref = '/settings',
}: AppSidebarFooterProps) {
  return (
    <div className="p-3 border-t border-border mt-auto shrink-0">
      <div className={cn('flex items-center gap-3 mb-3', collapsed && 'justify-center')}>
        <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-primary font-medium shrink-0">
          {initial}
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{displayName}</p>
            <p className="text-xs text-muted-foreground capitalize">{role?.toLowerCase()}</p>
          </div>
        )}
      </div>

      <div
        className={cn(
          'flex gap-1',
          collapsed ? 'flex-col items-center' : 'items-center'
        )}
      >
        <Link
          to={settingsHref}
          onClick={onNavigate}
          title={collapsed ? 'Settings' : undefined}
          className={cn(
            'inline-flex items-center justify-center rounded-lg text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors',
            collapsed ? 'h-9 w-9' : 'flex-1 gap-2 px-3 py-2'
          )}
        >
          <Settings className="h-4 w-4 shrink-0" />
          {!collapsed && 'Settings'}
        </Link>
        <Button
          variant="ghost"
          size={collapsed ? 'icon' : 'sm'}
          onClick={onLogout}
          title={collapsed ? 'Logout' : undefined}
          className={cn(
            'text-muted-foreground hover:text-foreground',
            !collapsed && 'flex-1 justify-center gap-2'
          )}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && 'Logout'}
        </Button>
        <ThemeToggle />
      </div>
    </div>
  )
}
