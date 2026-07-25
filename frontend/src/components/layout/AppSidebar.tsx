import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Copy, Shield, Bot, MessageSquare, Search, PanelLeftClose } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { hasAdminAccess } from '@/lib/roles'
import { AppSidebarFooter } from './AppSidebarFooter'
import type { SessionSummary } from '@/api'

interface AppSidebarProps {
  className?: string
  variant?: 'chat' | 'settings'
  sessions: SessionSummary[]
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
  isSessionMutationDisabled?: boolean
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
  isSessionMutationDisabled = false,
}: AppSidebarProps) {
  const [searchQuery, setSearchQuery] = useState('')

  const filteredSessions = sessions.filter((s) =>
    s.session_id.toLowerCase().includes(searchQuery.toLowerCase().trim())
  )

  return (
    <div
      className={cn(
        'border-r border-border/40 bg-card/60 backdrop-blur flex flex-col h-full select-none',
        className
      )}
    >
      <div className="p-3.5 border-b border-border/40 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          {(showCloseButton ?? true) && onClose && (
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="h-8 w-8 text-muted-foreground hover:text-foreground shrink-0"
              title="Collapse sidebar"
              aria-label="Close sidebar"
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          )}
          <div className="p-1.5 rounded-xl bg-primary/10 border border-primary/20 shrink-0">
            <Bot className="h-4 w-4 text-primary" />
          </div>
          <span className="font-bold text-base tracking-tight truncate">RootAgent</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {hasAdminAccess(userRole) && (
            <Button variant="ghost" size="icon" className="h-8 w-8" asChild title="Admin">
              <Link to="/admin" onClick={onClose}>
                <Shield className="h-4 w-4 text-muted-foreground hover:text-foreground" />
              </Link>
            </Button>
          )}
        </div>
      </div>

      {variant === 'settings' ? (
        <div className="p-2">
          <Button variant="ghost" className="w-full justify-start gap-2 rounded-xl" asChild>
            <Link to="/" onClick={onClose}>
              <MessageSquare className="h-4 w-4" />
              Back to chat
            </Link>
          </Button>
        </div>
      ) : (
        <div className="p-3 space-y-3 shrink-0">
          <Button
            onClick={onCreateSession}
            disabled={isSessionMutationDisabled}
            className="w-full justify-center gap-2 rounded-xl bg-primary/15 text-primary hover:bg-primary/25 border border-primary/20 font-medium h-9 text-xs transition-all"
          >
            <Plus className="h-4 w-4" />
            New Chat
          </Button>

          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground/60" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search threads..."
              className="w-full rounded-xl border border-border/40 bg-muted/30 pl-8 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-all"
            />
          </div>
        </div>
      )}

      {variant === 'chat' && (
        <>
          <div className="px-3 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
            Recent Threads
          </div>

          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2 space-y-1">
              {filteredSessions.length === 0 && (
                <div className="p-4 text-center text-xs text-muted-foreground/70">
                  {searchQuery ? 'No matching threads.' : 'No chat history yet.'}
                </div>
              )}
              {filteredSessions.map((session) => {
                const sid = session.session_id
                const unavailable = isSessionMutationDisabled || session.deletion_pending
                const isSelected = currentSessionId === sid

                return (
                  <div
                    key={sid}
                    onClick={() => {
                      if (!unavailable) onSelectSession(sid)
                    }}
                    aria-disabled={unavailable}
                    className={cn(
                      'group flex items-center justify-between gap-1.5 px-3 py-2 rounded-xl cursor-pointer transition-all overflow-hidden text-xs w-full min-w-0',
                      isSelected
                        ? 'bg-primary/15 text-primary font-medium border border-primary/20'
                        : 'hover:bg-muted/60 text-muted-foreground hover:text-foreground border border-transparent',
                      unavailable && 'cursor-not-allowed opacity-50'
                    )}
                  >
                    <span className="w-0 flex-1 truncate font-mono text-xs" title={sid}>
                      {session.deletion_pending ? 'Deleting…' : sid}
                    </span>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 rounded-lg hover:bg-background/80"
                        onClick={(e) => onCopySessionId(sid, e)}
                        title="Copy session ID"
                      >
                        <Copy className="h-3 w-3 text-muted-foreground" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 rounded-lg text-destructive hover:bg-destructive/10"
                        disabled={session.deletion_pending}
                        onClick={(e) => onDeleteSession(sid, e)}
                        title="Delete chat"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                )
              })}
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
