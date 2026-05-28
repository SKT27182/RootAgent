import { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import type { Message as MessageType } from '@/types'
import {
  getSessions,
  deleteSession,
  getHistory,
  listArtifacts,
  uploadArtifact,
  deleteArtifact,
  type ArtifactItem,
} from '@/api'
import { useChatWebSocket } from '@/hooks/useChatWebSocket'
import { normalizeHistoryMessages } from '@/lib/parse-history'
import { useAuth } from '@/lib/auth-context'
import { userDisplayName, userInitial } from '@/lib/display'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { ChatMain } from '@/components/chat/ChatMain'
import { ControlPanel } from '@/components/chat/ControlPanel'

export default function Chat() {
  const { user, logout } = useAuth()
  const userId = user?.id || 'anonymous'
  const [sessions, setSessions] = useState<string[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageType[]>([])
  const [input, setInput] = useState('')
  const [useReasoning, setUseReasoning] = useState(true)
  const [showReasoning, setShowReasoning] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  const [chatError, setChatError] = useState('')
  useDocumentTitle('Chat — RootAgent')

  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(false)
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const artifactInputRef = useRef<HTMLInputElement>(null)
  const [csvFile, setCsvFile] = useState<{ name: string; content: string } | null>(null)
  const [images, setImages] = useState<{ name: string; base64: string }[]>([])
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([])
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([])

  const appendStepMessage = (msg: MessageType) => {
    setMessages((prev) => [...prev, msg])
  }

  const { send: sendWsChat } = useChatWebSocket({
    onStep: appendStepMessage,
    onSessionId: (id) => {
      if (!currentSessionId) {
        setCurrentSessionId(id)
        void refreshSessions()
      }
    },
    onError: (message) => setChatError(message),
    onDone: () => setIsStreaming(false),
  })

  useEffect(() => {
    if (userId !== 'anonymous') {
      void refreshSessions()
    }
  }, [userId])

  useEffect(() => {
    if (currentSessionId) {
      void loadHistory(currentSessionId)
      void loadArtifacts(currentSessionId)
      setIsLeftSidebarOpen(false)
    } else {
      setMessages([])
      setArtifacts([])
      setSelectedArtifactIds([])
    }
  }, [currentSessionId])

  useEffect(() => {
    scrollToBottom()
  }, [messages, isStreaming, showReasoning])

  const scrollToBottom = () => {
    setTimeout(() => {
      scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 100)
  }

  const refreshSessions = async () => {
    try {
      const sess = await getSessions(userId)
      setSessions(sess)
    } catch (error) {
      console.error('Failed to load sessions', error)
    }
  }

  const loadHistory = async (sessionId: string) => {
    try {
      const hist = await getHistory(userId, sessionId, true)
      setMessages(normalizeHistoryMessages(hist))
    } catch (error) {
      console.error('Failed to load history', error)
    }
  }

  const loadArtifacts = async (sessionId: string) => {
    try {
      const items = await listArtifacts(sessionId)
      setArtifacts(items)
    } catch (error) {
      console.error('Failed to load artifacts', error)
    }
  }

  const handleCreateSession = () => {
    setCurrentSessionId(null)
    setMessages([])
    setIsLeftSidebarOpen(false)
  }

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to delete this session?')) {
      await deleteSession(userId, sessionId)
      await refreshSessions()
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null)
        setMessages([])
      }
    }
  }

  const handleCopySessionId = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    void navigator.clipboard.writeText(sessionId)
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''

    if (!currentSessionId) {
      alert('Send a message first to create a session, then upload files.')
      return
    }

    try {
      const artifact = await uploadArtifact(currentSessionId, file)
      setArtifacts((prev) => [artifact, ...prev])
      setSelectedArtifactIds((prev) => [...prev, artifact.id])
      if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
        const reader = new FileReader()
        reader.onload = (ev) => {
          const content = ev.target?.result as string
          setCsvFile({ name: file.name, content })
        }
        reader.readAsText(file)
      }
    } catch (error) {
      console.error('Upload failed', error)
      alert('Failed to upload file')
    }
  }

  const handleArtifactUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !currentSessionId) return
    e.target.value = ''
    try {
      const artifact = await uploadArtifact(currentSessionId, file)
      setArtifacts((prev) => [artifact, ...prev])
      setSelectedArtifactIds((prev) => [...prev, artifact.id])
    } catch (error) {
      console.error('Artifact upload failed', error)
    }
  }

  const handleDeleteArtifact = async (artifactId: string) => {
    if (!currentSessionId) return
    await deleteArtifact(currentSessionId, artifactId)
    setArtifacts((prev) => prev.filter((a) => a.id !== artifactId))
    setSelectedArtifactIds((prev) => prev.filter((id) => id !== artifactId))
  }

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) {
      Array.from(files).forEach((file) => {
        if (!file.type.startsWith('image/')) {
          alert('Please upload image files only')
          return
        }
        const reader = new FileReader()
        reader.onload = (event) => {
          const base64 = event.target?.result as string
          setImages((prev) => [...prev, { name: file.name, base64 }])
        }
        reader.readAsDataURL(file)
      })
    }
    e.target.value = ''
  }

  const sendMessage = () => {
    if (!input.trim() || isStreaming) return

    const payload = {
      query: input,
      user_id: userId,
      session_id: currentSessionId,
      include_reasoning: useReasoning,
      images: images.length > 0 ? images.map((img) => img.base64) : null,
      csv_data: csvFile ? csvFile.content : null,
      artifact_ids: selectedArtifactIds.length > 0 ? selectedArtifactIds : null,
    }

    const attachmentInfo = [
      csvFile ? `[CSV: ${csvFile.name}]` : '',
      images.length > 0 ? `[${images.length} image(s)]` : '',
    ]
      .filter(Boolean)
      .join(' ')

    const userMsg: MessageType = {
      role: 'user',
      content: input + (attachmentInfo ? `\n\n${attachmentInfo}` : ''),
      step_kind: 'user',
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setCsvFile(null)
    setImages([])
    setChatError('')
    setIsStreaming(true)
    void sendWsChat(payload)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-[100dvh] w-full bg-background text-foreground overflow-hidden relative">
      {(isLeftSidebarOpen || isRightSidebarOpen) && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => {
            setIsLeftSidebarOpen(false)
            setIsRightSidebarOpen(false)
          }}
        />
      )}

      <AppSidebar
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 transition-transform duration-300 ease-in-out md:relative md:translate-x-0 md:flex shrink-0',
          isLeftSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        )}
        sessions={sessions}
        currentSessionId={currentSessionId}
        displayName={userDisplayName(user)}
        userInitial={userInitial(user)}
        userRole={user?.role}
        onSelectSession={setCurrentSessionId}
        onCreateSession={handleCreateSession}
        onDeleteSession={handleDeleteSession}
        onCopySessionId={handleCopySessionId}
        onLogout={logout}
        onClose={() => setIsLeftSidebarOpen(false)}
        showCloseButton
      />

      <ChatMain
        scrollRef={scrollRef}
        messages={messages}
        showReasoning={showReasoning}
        isStreaming={isStreaming}
        chatError={chatError}
        input={input}
        onInputChange={setInput}
        onSend={sendMessage}
        onKeyDown={handleKeyDown}
        csvFile={csvFile}
        onClearCsv={() => setCsvFile(null)}
        images={images}
        onRemoveImage={(idx) =>
          setImages((prev) => prev.filter((_, i) => i !== idx))
        }
        fileInputRef={fileInputRef}
        imageInputRef={imageInputRef}
        onFileSelect={handleFileSelect}
        onImageSelect={handleImageSelect}
        onOpenLeftSidebar={() => setIsLeftSidebarOpen(true)}
        onOpenRightSidebar={() => setIsRightSidebarOpen(true)}
      />

      <input
        type="file"
        ref={artifactInputRef}
        className="hidden"
        onChange={handleArtifactUpload}
      />

      <ControlPanel
        className={cn(
          'fixed inset-y-0 right-0 z-50 w-72 transition-transform duration-300 ease-in-out md:relative md:translate-x-0 md:flex shrink-0',
          isRightSidebarOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
        )}
        showCloseButton
        onClose={() => setIsRightSidebarOpen(false)}
        useReasoning={useReasoning}
        onUseReasoningChange={setUseReasoning}
        showReasoning={showReasoning}
        onShowReasoningChange={setShowReasoning}
        currentSessionId={currentSessionId}
        artifacts={artifacts}
        selectedArtifactIds={selectedArtifactIds}
        onSelectedArtifactIdsChange={setSelectedArtifactIds}
        onArtifactUploadClick={() => artifactInputRef.current?.click()}
        onDeleteArtifact={handleDeleteArtifact}
        onCopySessionId={handleCopySessionId}
        isStreaming={isStreaming}
      />
    </div>
  )
}
