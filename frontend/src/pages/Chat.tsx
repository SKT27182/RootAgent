import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createSession,
  deleteArtifact,
  deleteSession,
  downloadArtifact,
  getClientError,
  getHistory,
  getSessions,
  listArtifacts,
  uploadArtifact,
  type ArtifactItem,
  type SessionSummary,
} from '@/api'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { ChatMain } from '@/components/chat/ChatMain'
import { ControlPanel } from '@/components/chat/ControlPanel'
import { useChatWebSocket } from '@/hooks/useChatWebSocket'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  validateArtifactUpload,
} from '@/lib/artifacts'
import { useAuth } from '@/lib/auth-types'
import { userDisplayName, userInitial } from '@/lib/display'
import type { DoneEvent, ErrorEvent, RunStartedEvent, StepEvent, ToolEvent } from '@/lib/chat-protocol'
import { normalizeHistoryMessages, traceOnlyStep } from '@/lib/parse-history'
import { cn } from '@/lib/utils'
import type { Message as MessageType } from '@/types'

export default function Chat() {
  const { user, logout } = useAuth()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageType[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [chatError, setChatError] = useState('')
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([])
  const [artifactStatus, setArtifactStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [artifactOperationError, setArtifactOperationError] = useState('')
  const [artifactReload, setArtifactReload] = useState(0)
  const currentSessionDeleting = sessions.some(
    (session) => session.session_id === currentSessionId && session.deletion_pending
  )

  const scrollRef = useRef<HTMLDivElement>(null)
  const artifactInputRef = useRef<HTMLInputElement>(null)
  const sessionLoadGeneration = useRef(0)
  const currentSessionRef = useRef<string | null>(null)
  const skipSessionLoadRef = useRef<string | null>(null)
  useDocumentTitle('Chat — RootAgent')

  const refreshSessions = useCallback(async (signal?: AbortSignal) => {
    try {
      setSessions(await getSessions(signal))
    } catch (error) {
      if (!signal?.aborted) console.error('Failed to load sessions', error)
    }
  }, [])

  const selectSession = useCallback(
    (sessionId: string | null) => {
      if (isStreaming) return
      skipSessionLoadRef.current = null
      currentSessionRef.current = sessionId
      setCurrentSessionId(sessionId)
      setMessages([])
      setArtifacts([])
      setArtifactOperationError('')
      setArtifactStatus(sessionId ? 'loading' : 'idle')
    },
    [isStreaming]
  )

  const handleRunStarted = useCallback((event: RunStartedEvent) => {
    if (currentSessionRef.current !== event.session_id) {
      skipSessionLoadRef.current = event.session_id
      setArtifactStatus('idle')
      currentSessionRef.current = event.session_id
      setCurrentSessionId(event.session_id)
    }
    void refreshSessions()
  }, [refreshSessions])

  const handleStep = useCallback((event: StepEvent) => {
    // `done` remains the sole source of the final answer. Preserve thinking and
    // code carried by the persisted final step as a separate trace card.
    const displayedStep = event.step.is_final_answer
      ? traceOnlyStep(event.step)
      : event.step
    if (!displayedStep) return
    setMessages((previous) => [
      ...previous,
      {
        role: 'assistant',
        content: JSON.stringify(displayedStep),
        step_kind: 'assistant',
        timestamp: new Date().toISOString(),
        message_id: `${event.run_id}:${event.step_index}:step`,
        step_index: event.step_index,
      },
    ])
  }, [])

  const handleTool = useCallback((event: ToolEvent) => {
    setMessages((previous) => [
      ...previous,
      {
        role: 'assistant',
        content: JSON.stringify({ output: event.observation }),
        step_kind: 'tool',
        timestamp: new Date().toISOString(),
        message_id: `${event.run_id}:${event.step_index}:tool`,
        step_index: event.step_index,
      },
    ])
  }, [])

  const handleArtifactEvent = useCallback((artifact: ArtifactItem) => {
    setArtifacts((previous) => [artifact, ...previous.filter((item) => item.id !== artifact.id)])
  }, [])

  const handleChatError = useCallback((event: ErrorEvent) => {
    const suffix = event.correlation_id ? ` (reference ${event.correlation_id})` : ''
    setChatError(`${event.message}${suffix}`)
    skipSessionLoadRef.current = null
    setIsStreaming(false)
  }, [])

  const handleChatDone = useCallback((event: DoneEvent) => {
    setMessages((previous) => [
      ...previous,
      {
        role: 'assistant',
        content: JSON.stringify({
          thinking: '',
          final_answer: event.final_answer,
          is_final_answer: true,
        }),
        step_kind: 'assistant',
        timestamp: new Date().toISOString(),
        message_id: event.message_id,
        artifact_ids: event.generated_artifact_ids,
      },
    ])
    skipSessionLoadRef.current = null
    setIsStreaming(false)
    void refreshSessions()
    const generation = ++sessionLoadGeneration.current
    void getHistory(event.session_id)
      .then((history) => {
        if (
          currentSessionRef.current === event.session_id &&
          generation === sessionLoadGeneration.current
        ) {
          setMessages(normalizeHistoryMessages(history))
        }
      })
      .catch((error) => {
        // The terminal answer is already visible; a history reconciliation
        // failure must not turn a successful run into a client-visible failure.
        console.error('Failed to reconcile completed chat history', error)
      })
  }, [refreshSessions])

  const { send: sendWsChat, close: closeChat } = useChatWebSocket({
    onRunStarted: handleRunStarted,
    onStep: handleStep,
    onTool: handleTool,
    onArtifact: handleArtifactEvent,
    onError: handleChatError,
    onDone: handleChatDone,
  })

  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    void getSessions(controller.signal)
      .then(setSessions)
      .catch((error) => {
        if (!controller.signal.aborted) console.error('Failed to load sessions', error)
      })
    return () => controller.abort()
  }, [refreshSessions, user])

  useEffect(() => {
    if (!sessions.some((session) => session.deletion_pending)) return
    const timer = window.setInterval(() => void refreshSessions(), 1_000)
    return () => window.clearInterval(timer)
  }, [refreshSessions, sessions])

  useEffect(() => {
    if (
      currentSessionId &&
      sessions.length > 0 &&
      !sessions.some((session) => session.session_id === currentSessionId) &&
      !isStreaming
    ) {
      const timer = window.setTimeout(() => selectSession(null), 0)
      return () => window.clearTimeout(timer)
    }
  }, [currentSessionId, isStreaming, selectSession, sessions])

  useEffect(() => {
    if (!currentSessionId) return
    const skipHistory =
      skipSessionLoadRef.current === currentSessionId || isStreaming
    const controller = new AbortController()
    const generation = ++sessionLoadGeneration.current

    // Keep skipSessionLoadRef set for the whole first-run stream so React
    // StrictMode remounts cannot clear it and wipe live WebSocket bubbles.
    if (!skipHistory) {
      void getHistory(currentSessionId, controller.signal)
        .then((history) => {
          if (!controller.signal.aborted && generation === sessionLoadGeneration.current) {
            setMessages(normalizeHistoryMessages(history))
          }
        })
        .catch((error) => {
          if (!controller.signal.aborted) {
            console.error('Failed to load history', error)
            setChatError('Could not load this chat history.')
          }
        })
    }

    void listArtifacts(currentSessionId, controller.signal)
      .then((items) => {
        if (controller.signal.aborted || generation !== sessionLoadGeneration.current) return
        setArtifacts(items)
        setArtifactStatus('idle')
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          console.error('Failed to load artifacts', error)
          setArtifactStatus('error')
        }
      })

    return () => controller.abort()
  }, [currentSessionId, artifactReload, isStreaming])

  useEffect(() => {
    const timer = window.setTimeout(() => scrollRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    return () => window.clearTimeout(timer)
  }, [messages, isStreaming])

  const handleCreateSession = () => {
    selectSession(null)
    if (window.innerWidth < 768) {
      setIsLeftSidebarOpen(false)
    }
  }

  const handleDeleteSession = async (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation()
    if (!window.confirm('Are you sure you want to delete this session?')) return
    try {
      const result = await deleteSession(sessionId)
      await refreshSessions()
      if (result.status === 'deleted' && currentSessionId === sessionId) selectSession(null)
    } catch (error) {
      setChatError(getClientError(error).message)
    }
  }

  const handleCopySessionId = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation()
    void navigator.clipboard.writeText(sessionId)
  }

  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentSessionRef.current) return currentSessionRef.current
    const created = await createSession()
    skipSessionLoadRef.current = created.session_id
    currentSessionRef.current = created.session_id
    setCurrentSessionId(created.session_id)
    setArtifactStatus('idle')
    await refreshSessions()
    return created.session_id
  }, [refreshSessions])

  const handleArtifactUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || isStreaming || currentSessionDeleting) return
    const validation = validateArtifactUpload(file)
    if (!validation.ok) {
      setArtifactOperationError(validation.message)
      return
    }
    setArtifactOperationError('')
    try {
      const sessionId = await ensureSession()
      const artifact = await uploadArtifact(sessionId, file)
      setArtifacts((previous) => [artifact, ...previous.filter((item) => item.id !== artifact.id)])
    } catch (error) {
      setArtifactOperationError(getClientError(error).message)
    }
  }

  const handleDeleteArtifact = async (artifact: ArtifactItem) => {
    if (!currentSessionId || isStreaming) return
    setArtifactOperationError('')
    try {
      await deleteArtifact(currentSessionId, artifact.id)
      setArtifacts((previous) => previous.filter((item) => item.id !== artifact.id))
    } catch (error) {
      setArtifactOperationError(getClientError(error).message)
    }
  }

  const handleDownloadArtifact = async (artifact: ArtifactItem) => {
    setArtifactOperationError('')
    try {
      await downloadArtifact(artifact)
    } catch (error) {
      setArtifactOperationError(getClientError(error).message)
    }
  }

  const sendMessage = () => {
    const query = input.trim()
    if (!query || isStreaming || currentSessionDeleting) return
    const payload = {
      request_id: crypto.randomUUID(),
      query: query.slice(0, 20_000),
      session_id: currentSessionId,
    }
    setMessages((previous) => [
      ...previous,
      {
        role: 'user',
        content: query,
        step_kind: 'user',
        timestamp: new Date().toISOString(),
      },
    ])
    setInput('')
    setChatError('')
    setIsStreaming(true)
    void sendWsChat(payload)
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  const [leftWidth, setLeftWidth] = useState(260)
  const [rightWidth, setRightWidth] = useState(280)
  const [isResizingLeft, setIsResizingLeft] = useState(false)
  const [isResizingRight, setIsResizingRight] = useState(false)

  useEffect(() => {
    if (!isResizingLeft && !isResizingRight) return

    const handleMouseMove = (e: MouseEvent) => {
      if (isResizingLeft) {
        const newWidth = Math.max(180, Math.min(500, e.clientX))
        setLeftWidth(newWidth)
      } else if (isResizingRight) {
        const newWidth = Math.max(200, Math.min(500, window.innerWidth - e.clientX))
        setRightWidth(newWidth)
      }
    }

    const handleMouseUp = () => {
      setIsResizingLeft(false)
      setIsResizingRight(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizingLeft, isResizingRight])

  const handleLogout = () => {
    closeChat()
    logout()
  }

  return (
    <div
      className={cn(
        'relative flex h-[100dvh] w-full overflow-hidden bg-background text-foreground',
        (isResizingLeft || isResizingRight) && 'select-none cursor-col-resize'
      )}
    >
      {(isLeftSidebarOpen || isRightSidebarOpen) && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => {
            setIsLeftSidebarOpen(false)
            setIsRightSidebarOpen(false)
          }}
        />
      )}

      <div
        style={{ width: isLeftSidebarOpen ? `${leftWidth}px` : undefined }}
        className={cn(
          'relative shrink-0 transition-all duration-300 ease-in-out h-full',
          isLeftSidebarOpen ? 'translate-x-0 md:block' : '-translate-x-full md:hidden'
        )}
      >
        <AppSidebar
          className="w-full h-full"
          sessions={sessions}
          currentSessionId={currentSessionId}
          displayName={userDisplayName(user)}
          userInitial={userInitial(user)}
          userRole={user?.role}
          isSessionMutationDisabled={isStreaming}
          onSelectSession={(sessionId) => {
            selectSession(sessionId)
            if (window.innerWidth < 768) {
              setIsLeftSidebarOpen(false)
            }
          }}
          onCreateSession={handleCreateSession}
          onDeleteSession={handleDeleteSession}
          onCopySessionId={handleCopySessionId}
          onLogout={handleLogout}
          onClose={() => setIsLeftSidebarOpen(false)}
          showCloseButton
        />
        {isLeftSidebarOpen && (
          <div
            className="hidden md:block absolute right-0 top-0 bottom-0 w-2 cursor-col-resize hover:bg-primary/50 active:bg-primary z-50 transition-colors group"
            onMouseDown={(e) => {
              e.preventDefault()
              setIsResizingLeft(true)
            }}
            onDoubleClick={() => setLeftWidth(260)}
            title="Drag to resize sidebar (double click to reset)"
          />
        )}
      </div>

      <ChatMain
        scrollRef={scrollRef}
        messages={messages}
        isStreaming={isStreaming}
        isSessionDeleting={currentSessionDeleting}
        chatError={chatError}
        input={input}
        onInputChange={setInput}
        onSend={sendMessage}
        onKeyDown={handleKeyDown}
        canUpload={!isStreaming && !currentSessionDeleting}
        onUploadClick={() => artifactInputRef.current?.click()}
        isLeftSidebarOpen={isLeftSidebarOpen}
        isRightSidebarOpen={isRightSidebarOpen}
        onToggleLeftSidebar={() => setIsLeftSidebarOpen((prev) => !prev)}
        onToggleRightSidebar={() => setIsRightSidebarOpen((prev) => !prev)}
        onOpenLeftSidebar={() => setIsLeftSidebarOpen(true)}
        onOpenRightSidebar={() => setIsRightSidebarOpen(true)}
      />

      <input
        type="file"
        ref={artifactInputRef}
        className="hidden"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        onChange={handleArtifactUpload}
      />

      <div
        style={{ width: isRightSidebarOpen ? `${rightWidth}px` : undefined }}
        className={cn(
          'relative shrink-0 transition-all duration-300 ease-in-out h-full',
          isRightSidebarOpen ? 'translate-x-0 md:block' : 'translate-x-full md:hidden'
        )}
      >
        {isRightSidebarOpen && (
          <div
            className="hidden md:block absolute left-0 top-0 bottom-0 w-2 cursor-col-resize hover:bg-primary/50 active:bg-primary z-50 transition-colors group"
            onMouseDown={(e) => {
              e.preventDefault()
              setIsResizingRight(true)
            }}
            onDoubleClick={() => setRightWidth(280)}
            title="Drag to resize artifacts panel (double click to reset)"
          />
        )}
        <ControlPanel
          key={currentSessionId ?? 'new-session'}
          className="w-full h-full"
          showCloseButton
          onClose={() => setIsRightSidebarOpen(false)}
          currentSessionId={currentSessionId}
          artifacts={artifacts}
          artifactStatus={artifactStatus}
          artifactOperationError={artifactOperationError}
          onArtifactUploadClick={() => artifactInputRef.current?.click()}
          onDeleteArtifact={(artifact) => void handleDeleteArtifact(artifact)}
          onDownloadArtifact={(artifact) => void handleDownloadArtifact(artifact)}
          onRetryArtifacts={() => {
            setArtifactStatus('loading')
            setArtifactReload((value) => value + 1)
          }}
          onCopySessionId={handleCopySessionId}
          isStreaming={isStreaming || currentSessionDeleting}
        />
      </div>
    </div>
  )
}
