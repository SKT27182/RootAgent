import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  ArrowUp,
  Loader2,
  Paperclip,
  Sparkles,
  Compass,
  Code2,
  GraduationCap,
  Bot,
  PanelLeft,
  PanelRight,
} from 'lucide-react'
import type { Message as MessageType } from '@/types'
import {
  AgentWorkTrace,
  ChatMessageBubble,
  type TraceStepPart,
} from '@/components/ChatMessageBubble'
import { parseAgentStep, parseToolOutput } from '@/lib/parse-history'

interface ChatMainProps {
  scrollRef: React.RefObject<HTMLDivElement | null>
  messages: MessageType[]
  isStreaming: boolean
  isSessionDeleting?: boolean
  chatError: string
  input: string
  onInputChange: (v: string) => void
  onSend: () => void
  onKeyDown: (e: React.KeyboardEvent) => void
  canUpload: boolean
  onUploadClick: () => void
  isLeftSidebarOpen?: boolean
  isRightSidebarOpen?: boolean
  onToggleLeftSidebar?: () => void
  onToggleRightSidebar?: () => void
  onOpenLeftSidebar: () => void
  onOpenRightSidebar: () => void
}

type DisplayBlock =
  | { kind: 'user'; key: string; message: MessageType }
  | { kind: 'final'; key: string; message: MessageType }
  | { kind: 'trace_group'; key: string; parts: TraceStepPart[] }

function messageKey(message: MessageType, index: number): string {
  return message.message_id ?? `message-${index}`
}

function isTraceAssistant(message: MessageType): boolean {
  return (
    message.step_kind === 'assistant' &&
    !parseAgentStep(message.content).is_final_answer
  )
}

function pairedObservation(
  message: MessageType,
  next: MessageType | undefined
): string | undefined {
  if (!next || next.step_kind !== 'tool' || !isTraceAssistant(message)) return undefined
  const sameIndex =
    (message.step_index != null && message.step_index === next.step_index) ||
    (message.step_index == null && next.step_index == null)
  return sameIndex ? parseToolOutput(next.content) : undefined
}

export function groupMessagesIntoBlocks(messages: MessageType[]): DisplayBlock[] {
  const blocks: DisplayBlock[] = []
  let pendingParts: TraceStepPart[] = []
  let pendingKey: string | null = null

  const flushTrace = () => {
    if (!pendingParts.length || !pendingKey) return
    blocks.push({ kind: 'trace_group', key: pendingKey, parts: pendingParts })
    pendingParts = []
    pendingKey = null
  }

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    const key = messageKey(message, index)

    if (message.step_kind === 'user') {
      flushTrace()
      blocks.push({ kind: 'user', key, message })
      continue
    }

    if (message.step_kind === 'assistant' && parseAgentStep(message.content).is_final_answer) {
      flushTrace()
      blocks.push({ kind: 'final', key, message })
      continue
    }

    if (isTraceAssistant(message)) {
      const next = index + 1 < messages.length ? messages[index + 1] : undefined
      const observation = pairedObservation(message, next)
      if (!pendingKey) pendingKey = `trace:${key}`
      pendingParts.push({
        key,
        step: parseAgentStep(message.content),
        observation,
      })
      if (observation) index += 1
      continue
    }

    if (message.step_kind === 'tool') {
      if (!pendingKey) pendingKey = `trace:${key}`
      pendingParts.push({
        key,
        step: {
          thinking: '',
          code: null,
          final_answer: null,
          is_final_answer: false,
        },
        observation: parseToolOutput(message.content),
      })
      continue
    }

    flushTrace()
  }

  flushTrace()
  return blocks
}

function currentTurnTraceKey(blocks: DisplayBlock[]): string | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.kind === 'user') return null
    if (block.kind === 'trace_group') return block.key
  }
  return null
}

function MessageTimeline({
  blocks,
  autoExpandedKey,
  isStreaming,
}: {
  blocks: DisplayBlock[]
  autoExpandedKey: string | null
  isStreaming: boolean
}) {
  const [expansionOverrides, setExpansionOverrides] = useState<Map<string, boolean>>(
    () => new Map()
  )

  return blocks.map((block) => {
    if (block.kind === 'user' || block.kind === 'final') {
      return <ChatMessageBubble key={block.key} msg={block.message} />
    }

    const expanded = expansionOverrides.has(block.key)
      ? Boolean(expansionOverrides.get(block.key))
      : autoExpandedKey === block.key

    return (
      <div key={block.key} className="flex flex-col items-start w-full">
        <AgentWorkTrace
          parts={block.parts}
          expanded={expanded}
          streaming={isStreaming && autoExpandedKey === block.key}
          onExpandedChange={(nextExpanded) => {
            setExpansionOverrides((previous) => {
              const next = new Map(previous)
              next.set(block.key, nextExpanded)
              return next
            })
          }}
        />
      </div>
    )
  })
}

const PROMPT_SUGGESTIONS = [
  'Analyze my CSV dataset and summarize key insights',
  'Write a Python data processing pipeline',
  'Explain machine learning model architectures',
  'Debug an error in my code snippet',
]

export function ChatMain({
  scrollRef,
  messages,
  isStreaming,
  isSessionDeleting = false,
  chatError,
  input,
  onInputChange,
  onSend,
  onKeyDown,
  canUpload,
  onUploadClick,
  isLeftSidebarOpen = true,
  isRightSidebarOpen = true,
  onToggleLeftSidebar,
  onToggleRightSidebar,
  onOpenLeftSidebar,
  onOpenRightSidebar,
}: ChatMainProps) {
  const blocks = groupMessagesIntoBlocks(messages)
  const currentTraceKey = isStreaming ? currentTurnTraceKey(blocks) : null
  const settledKey = blocks.length ? blocks[blocks.length - 1].key : 'empty'
  const timelineKey = isStreaming
    ? `stream:${currentTraceKey ?? 'pending'}`
    : `settled:${settledKey}`

  return (
    <div className="flex-1 flex flex-col relative min-h-0 w-full min-w-0 bg-background">
      <div className="h-14 border-b border-border/40 flex items-center justify-between px-4 bg-background/80 backdrop-blur shrink-0 z-10">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-foreground"
            onClick={onToggleLeftSidebar ?? onOpenLeftSidebar}
            aria-label={isLeftSidebarOpen ? 'Hide sidebar' : 'Open sidebar'}
            title={isLeftSidebarOpen ? 'Hide sidebar' : 'Open sidebar'}
          >
            <PanelLeft className="h-5 w-5" />
          </Button>
          <span className="font-semibold text-sm tracking-tight">RootAgent</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground hover:text-foreground"
          onClick={onToggleRightSidebar ?? onOpenRightSidebar}
          aria-label={isRightSidebarOpen ? 'Hide artifacts' : 'Open artifacts'}
          title={isRightSidebarOpen ? 'Hide artifacts' : 'Open artifacts'}
        >
          <PanelRight className="h-5 w-5" />
        </Button>
      </div>

      {chatError && (
        <div className="mx-4 mt-3 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive shadow-sm">
          {chatError}
        </div>
      )}
      {isSessionDeleting && (
        <div className="mx-4 mt-3 rounded-xl border border-border bg-muted/50 px-4 py-2.5 text-sm text-muted-foreground shadow-sm">
          This chat is waiting for its active run to finish before deletion.
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col">
        <ScrollArea className="flex-1 h-full w-full">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6 pb-28">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center min-h-[50vh] text-center pt-8 space-y-8">
                <div className="space-y-3">
                  <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-primary/10 mb-2">
                    <Bot className="h-8 w-8 text-primary" />
                  </div>
                  <h1 className="text-3xl font-bold tracking-tight sm:text-4xl text-foreground">
                    How can I help you?
                  </h1>
                  <p className="text-sm text-muted-foreground max-w-md mx-auto">
                    Ask questions, analyze data files, run Python analysis, or write clean code.
                  </p>
                </div>

                <div className="flex flex-wrap items-center justify-center gap-2 max-w-lg">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/40">
                    <Sparkles className="h-3.5 w-3.5 text-primary" /> Create
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/40">
                    <Compass className="h-3.5 w-3.5 text-primary" /> Explore
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/40">
                    <Code2 className="h-3.5 w-3.5 text-primary" /> Code
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/40">
                    <GraduationCap className="h-3.5 w-3.5 text-primary" /> Learn
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-xl text-left pt-2">
                  {PROMPT_SUGGESTIONS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => onInputChange(prompt)}
                      className="p-3.5 rounded-xl border border-border/50 bg-card/40 hover:bg-card hover:border-primary/40 text-xs font-medium text-muted-foreground hover:text-foreground transition-all duration-150 shadow-sm"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                <MessageTimeline
                  key={timelineKey}
                  blocks={blocks}
                  autoExpandedKey={currentTraceKey}
                  isStreaming={isStreaming}
                />
                {isStreaming && (
                  <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground px-1 py-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    Agent is working...
                  </div>
                )}
              </>
            )}
            <div ref={scrollRef} />
          </div>
        </ScrollArea>
      </div>

      {/* Floating integrated chat input container */}
      <div className="p-4 bg-gradient-to-t from-background via-background/95 to-transparent shrink-0">
        <div className="max-w-3xl mx-auto w-full">
          <div className="relative flex flex-col rounded-2xl border border-border/80 bg-card/90 shadow-2xl backdrop-blur-md focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/30 transition-all p-3">
            <Textarea
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Type a message..."
              maxLength={20_000}
              rows={2}
              className="w-full border-0 bg-transparent p-1 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 resize-none text-sm leading-relaxed placeholder:text-muted-foreground/60 min-h-[44px] max-h-[180px]"
              disabled={isStreaming || isSessionDeleting}
            />

            <div className="flex items-center justify-between pt-2 border-t border-border/30 mt-1">
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 rounded-full gap-1.5 px-3 text-xs text-muted-foreground hover:text-foreground hover:bg-muted"
                  onClick={onUploadClick}
                  disabled={isStreaming || isSessionDeleting || !canUpload}
                  title={canUpload ? 'Upload CSV or XLSX' : 'Upload unavailable while the agent is working'}
                >
                  <Paperclip className="h-3.5 w-3.5" />
                  <span>Attach</span>
                </Button>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-muted/60 text-muted-foreground">
                  <Sparkles className="h-3 w-3 text-primary" />
                  RootAgent v1
                </span>
              </div>

              <Button
                onClick={onSend}
                disabled={!input.trim() || isStreaming || isSessionDeleting}
                size="icon"
                className="h-8 w-8 rounded-full shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 transition-all disabled:opacity-30"
                aria-label="Send message"
              >
                {isStreaming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowUp className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
