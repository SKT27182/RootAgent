import type { AgentStep, Message } from '@/types'
import { normalizeMessageContent } from '@/lib/message-content'

export function parseAgentStep(content: string): AgentStep {
  return JSON.parse(content) as AgentStep
}

export function parseToolOutput(content: string): string {
  const data = JSON.parse(content) as { output?: string }
  return data.output ?? content
}

export function userDisplayText(content: string): string {
  return normalizeMessageContent(content)
}

export function shouldHideMessage(msg: Message, showReasoning: boolean): boolean {
  if (showReasoning) return false
  return msg.step_kind === 'tool' || Boolean(msg.step_kind === 'assistant' && msg.is_reasoning)
}

export function normalizeHistoryMessages(messages: Message[]): Message[] {
  return messages.map((msg) => {
    if (msg.step_kind === 'user') {
      return { ...msg, content: userDisplayText(msg.content) }
    }
    return msg
  })
}
