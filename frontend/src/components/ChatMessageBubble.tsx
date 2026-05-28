import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import {
  parseAgentStep,
  parseToolOutput,
  shouldHideMessage,
  userDisplayText,
} from '@/lib/parse-history'
import type { Message } from '@/types'

function preprocessMarkdown(content: string): string {
  let text = content
  text = text.replace(/([^\n])```/g, '$1\n```')
  text = text.replace(
    /^(?!.*!\[).*(data:image\/[a-zA-Z]+;base64,[^\s\)]+).*$/gm,
    '![Generated Image]($1)'
  )
  return text
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
      <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(uri) => uri}>
        {preprocessMarkdown(content)}
      </ReactMarkdown>
    </div>
  )
}

function StepBox({
  label,
  borderColor,
  titleColor,
  children,
}: {
  label: string
  borderColor: string
  titleColor: string
  children: React.ReactNode
}) {
  return (
    <Card
      className={cn(
        'p-4 shadow-sm w-full max-w-full bg-muted text-foreground border-l-4',
        borderColor
      )}
    >
      <div className={cn('text-xs font-mono uppercase mb-2', titleColor)}>
        {label}
      </div>
      {children}
    </Card>
  )
}

function AssistantStepView({ content }: { content: string }) {
  const step = parseAgentStep(content)

  return (
    <div className="flex flex-col gap-3 w-full max-w-full">
      {step.thinking?.trim() && (
        <StepBox
          label="Thinking..."
          borderColor="border-yellow-500"
          titleColor="text-yellow-600 dark:text-yellow-400"
        >
          <MarkdownBlock content={step.thinking} />
        </StepBox>
      )}
      {step.code?.trim() && (
        <StepBox
          label="Code"
          borderColor="border-emerald-500"
          titleColor="text-emerald-600 dark:text-emerald-400"
        >
          <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs dark:bg-zinc-900">
            <code className="font-mono text-foreground dark:text-zinc-100 whitespace-pre-wrap break-words">
              {step.code}
            </code>
          </pre>
        </StepBox>
      )}
      {step.is_final_answer && (
        <Card className="p-4 shadow-sm max-w-[85%] border border-border bg-card text-card-foreground">
          <MarkdownBlock content={step.final_answer ?? step.thinking} />
        </Card>
      )}
    </div>
  )
}

export function ChatMessageBubble({ msg }: { msg: Message; theme?: 'dark' | 'light' }) {
  if (msg.step_kind === 'user') {
    return (
      <div className="flex flex-col items-end">
        <Card
          className="p-4 max-w-[85%] shadow-sm border-0"
          style={{
            backgroundColor: 'var(--chat-user-bg)',
            color: 'hsl(var(--primary-foreground))',
          }}
        >
          <MarkdownBlock content={userDisplayText(msg.content)} inverted />
        </Card>
      </div>
    )
  }

  if (msg.step_kind === 'tool') {
    return (
      <div className="flex flex-col items-start w-full">
        <StepBox
          label="Tool"
          borderColor="border-blue-500"
          titleColor="text-blue-600 dark:text-blue-400"
        >
          <MarkdownBlock content={parseToolOutput(msg.content)} />
        </StepBox>
      </div>
    )
  }

  if (msg.step_kind === 'assistant') {
    return (
      <div className="flex flex-col items-start w-full">
        <AssistantStepView content={msg.content} />
      </div>
    )
  }

  return null
}

export { shouldHideMessage }
