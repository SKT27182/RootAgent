import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  parseAgentStep,
  userDisplayText,
} from '@/lib/parse-history'
import type { AgentStep, Message } from '@/types'
import { safeMarkdownUrl } from '@/lib/markdown-url'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { PythonCodeBlock } from '@/components/chat/PythonCodeBlock'

function preprocessMarkdown(content: string): string {
  return content.replace(/([^\n])```/g, '$1\n```')
}

const proseReadable =
  'prose-headings:text-inherit prose-p:text-inherit prose-strong:text-inherit prose-li:text-inherit prose-a:text-primary'

function MarkdownBlock({
  content,
  inverted = false,
}: {
  content: string
  inverted?: boolean
}) {
  return (
    <div
      className={cn(
        'prose max-w-none text-sm leading-relaxed break-words',
        proseReadable,
        inverted && 'prose-invert'
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeMarkdownUrl}
        components={{
          img: () => <span className="text-muted-foreground">[Use artifact Preview to view images]</span>,
        }}
      >
        {preprocessMarkdown(content)}
      </ReactMarkdown>
    </div>
  )
}

export type TraceStepPart = {
  key: string
  step: AgentStep
  observation?: string
}

function TraceBox({
  label,
  expanded,
  onExpandedChange,
  children,
}: {
  label: string
  borderColor?: string
  titleColor?: string
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'w-full max-w-full rounded-xl border border-border/60 bg-muted/30 overflow-hidden transition-all duration-200'
      )}
    >
      <Button
        type="button"
        variant="ghost"
        className="h-auto w-full justify-start rounded-none px-3.5 py-2.5 hover:bg-muted/60 transition-colors"
        aria-expanded={expanded}
        onClick={() => onExpandedChange(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="mr-2 h-4 w-4 text-muted-foreground transition-transform" />
        ) : (
          <ChevronRight className="mr-2 h-4 w-4 text-muted-foreground transition-transform" />
        )}
        <span className="text-xs font-mono font-medium tracking-wide uppercase text-muted-foreground hover:text-foreground">
          {label}
        </span>
      </Button>
      {expanded && <div className="space-y-4 border-t border-border/40 px-4 py-3.5 bg-background/40">{children}</div>}
    </div>
  )
}

function TraceStepDetails({ part }: { part: TraceStepPart }) {
  const { step, observation } = part
  return (
    <div className="space-y-3 border-l-2 border-primary/20 pl-3">
      {step.thinking?.trim() && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
            Thinking
          </div>
          <MarkdownBlock content={step.thinking} />
        </div>
      )}
      {step.code?.trim() && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
            Code
          </div>
          <PythonCodeBlock code={step.code} />
        </div>
      )}
      {observation?.trim() && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
            Observation
          </div>
          <MarkdownBlock content={observation} />
        </div>
      )}
    </div>
  )
}

export function AgentWorkTrace({
  parts,
  expanded,
  onExpandedChange,
  streaming = false,
}: {
  parts: TraceStepPart[]
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  streaming?: boolean
}) {
  const label = streaming
    ? `Working · ${parts.length} step${parts.length === 1 ? '' : 's'}`
    : `Thought process · ${parts.length} step${parts.length === 1 ? '' : 's'}`

  return (
    <TraceBox
      label={label}
      expanded={expanded}
      onExpandedChange={onExpandedChange}
    >
      <div className="space-y-4">
        {parts.map((part, index) => (
          <div key={part.key} className="space-y-2">
            {parts.length > 1 && (
              <div className="text-[11px] font-mono font-medium tracking-wider text-primary/80">
                Step {index + 1}
              </div>
            )}
            <TraceStepDetails part={part} />
          </div>
        ))}
      </div>
    </TraceBox>
  )
}

export function ChatMessageBubble({
  msg,
}: {
  msg: Message
  observation?: string
  traceExpanded?: boolean
  onTraceExpandedChange?: (expanded: boolean) => void
  theme?: 'dark' | 'light'
}) {
  if (msg.step_kind === 'user') {
    return (
      <div className="flex flex-col items-end w-full">
        <div
          className="px-4 py-3 max-w-[85%] rounded-2xl rounded-tr-sm shadow-sm text-sm leading-relaxed"
          style={{
            backgroundColor: 'var(--chat-user-bg)',
            color: 'hsl(var(--primary-foreground))',
          }}
        >
          <MarkdownBlock content={userDisplayText(msg.content)} inverted />
        </div>
      </div>
    )
  }

  if (msg.step_kind === 'assistant') {
    const step = parseAgentStep(msg.content)
    if (step.is_final_answer) {
      return (
        <div className="flex flex-col items-start w-full">
          <div className="p-4 rounded-2xl rounded-tl-sm max-w-[90%] border border-border/60 bg-card text-card-foreground shadow-sm">
            <MarkdownBlock content={step.final_answer ?? step.thinking} />
          </div>
        </div>
      )
    }
  }

  // Non-final assistant / tool messages are rendered via AgentWorkTrace groups.
  return null
}
