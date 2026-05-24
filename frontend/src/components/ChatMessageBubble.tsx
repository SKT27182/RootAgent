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

function MarkdownBlock({ content, theme }: { content: string; theme: 'dark' | 'light' }) {
  return (
    <div className={cn('prose max-w-none text-sm leading-relaxed break-words', theme === 'dark' && 'prose-invert')}>
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
    <Card className={cn('p-4 shadow-sm w-full max-w-full bg-muted/50 text-muted-foreground border-l-4', borderColor)}>
      <div className={cn('text-xs font-mono uppercase mb-2', titleColor)}>{label}</div>
      {children}
    </Card>
  )
}

function AssistantStepView({ content, theme }: { content: string; theme: 'dark' | 'light' }) {
  const step = parseAgentStep(content)

  return (
    <div className="flex flex-col gap-3 w-full max-w-full">
      {step.thinking?.trim() && (
        <StepBox label="Thinking..." borderColor="border-yellow-500" titleColor="text-yellow-500">
          <MarkdownBlock content={step.thinking} theme={theme} />
        </StepBox>
      )}
      {step.code?.trim() && (
        <StepBox label="Code" borderColor="border-emerald-500" titleColor="text-emerald-500">
          <pre className="overflow-x-auto rounded-md bg-zinc-950 p-4 text-xs">
            <code className="font-mono text-zinc-100 whitespace-pre-wrap break-words">{step.code}</code>
          </pre>
        </StepBox>
      )}
      {step.is_final_answer && (
        <Card className="p-4 shadow-sm bg-secondary max-w-[85%]">
          <MarkdownBlock content={step.final_answer ?? step.thinking} theme={theme} />
        </Card>
      )}
    </div>
  )
}

export function ChatMessageBubble({ msg, theme }: { msg: Message; theme: 'dark' | 'light' }) {
  if (msg.step_kind === 'user') {
    return (
      <div className="flex flex-col items-end">
        <Card className="p-4 max-w-[85%] shadow-sm bg-primary text-primary-foreground">
          <MarkdownBlock content={userDisplayText(msg.content)} theme={theme} />
        </Card>
      </div>
    )
  }

  if (msg.step_kind === 'tool') {
    return (
      <div className="flex flex-col items-start w-full">
        <StepBox label="Tool" borderColor="border-blue-500" titleColor="text-blue-500">
          <MarkdownBlock content={parseToolOutput(msg.content)} theme={theme} />
        </StepBox>
      </div>
    )
  }

  if (msg.step_kind === 'assistant') {
    return (
      <div className="flex flex-col items-start w-full">
        <AssistantStepView content={msg.content} theme={theme} />
      </div>
    )
  }

  return null
}

export { shouldHideMessage }
