import { Link } from 'react-router-dom'
import { Plus, Trash2, Copy, X, Shield, Bot, MessageSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { hasAdminAccess } from '@/lib/roles'
import { AppSidebarFooter } from './AppSidebarFooter'

interface AppSidebarProps {
  className?: string
  variant?: 'chat' | 'settings'
  sessions: string[]
  currentSessionId: string | null
  displayName?: string
  userInitial?: string
  userRole?: string
  onSelectSession: (id: string) => void
  onCreateSession: () => void
  onDeleteSession: (id: string, e: React.MouseEvent) => void
  onCopySessionId: (id: string, e: React.MouseEvent) => void
  onLogout: () => void
  onClose?: () => void
  showCloseButton?: boolean
}

export function AppSidebar({
  className,
  variant = 'chat',
  sessions,
  currentSessionId,
  displayName,
  userInitial: initial,
  userRole,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  onCopySessionId,
  onLogout,
  onClose,
  showCloseButton,
}: AppSidebarProps) {
  return (
    <div
      className={cn(
        'border-r border-border bg-card flex flex-col h-full',
        className
      )}
    >
      <div className="p-4 border-b border-border flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1.5 rounded-lg bg-primary/10">
            <Bot className="h-5 w-5 text-primary" />
          </div>
          <span className="font-bold text-lg truncate">RootAgent</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {hasAdminAccess(userRole) && (
            <Button variant="ghost" size="icon" asChild title="Admin">
              <Link to="/admin" onClick={onClose}>
                <Shield className="h-4 w-4" />
              </Link>
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={onCreateSession} title="New chat">
            <Plus className="h-5 w-5" />
          </Button>
          {showCloseButton && onClose && (
            <Button variant="ghost" size="icon" onClick={onClose} className="md:hidden">
              <X className="h-5 w-5" />
            </Button>
          )}
        </div>
      </div>

      {variant === 'settings' ? (
        <div className="p-2">
          <Button variant="ghost" className="w-full justify-start gap-2" asChild>
            <Link to="/" onClick={onClose}>
              <MessageSquare className="h-4 w-4" />
              Back to chat
            </Link>
          </Button>
        </div>
      ) : (
        <>
          <div className="px-4 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            Chats
          </div>

          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2 space-y-1">
              {sessions.length === 0 && (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  No chats found.
                </div>
              )}
              {sessions.map((sid) => (
            <div
              key={sid}
              onClick={() => onSelectSession(sid)}
              className={cn(
                'group flex items-center justify-between p-2.5 rounded-md cursor-pointer transition-colors overflow-hidden',
                currentSessionId === sid
                  ? 'bg-primary/10 text-primary'
                  : 'hover:bg-muted text-foreground'
              )}
            >
              <p className="truncate text-sm font-medium flex-1 min-w-0 mr-1">
                {sid.slice(0, 8)}…{sid.slice(-4)}
              </p>
              <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={(e) => onCopySessionId(sid, e)}
                >
                  <Copy className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-destructive hover:bg-destructive/10"
                  onClick={(e) => onDeleteSession(sid, e)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
              ))}
            </div>
          </ScrollArea>
        </>
      )}

      {variant === 'settings' && <div className="flex-1 min-h-0" />}

      <AppSidebarFooter
        displayName={displayName}
        userInitial={initial}
        role={userRole}
        onLogout={onLogout}
        onNavigate={onClose}
      />
    </div>
  )
}
