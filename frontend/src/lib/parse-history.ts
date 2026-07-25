import type { AgentStep, Message } from '@/types'
import { normalizeMessageContent } from '@/lib/message-content'

export function parseAgentStep(content: string): AgentStep {
  try {
    const parsed: unknown = JSON.parse(content)
    if (!parsed || typeof parsed !== 'object') throw new Error('Invalid agent step')
    const step = parsed as Partial<AgentStep>
    if (typeof step.is_final_answer !== 'boolean') throw new Error('Invalid agent step')
    return {
      thinking: typeof step.thinking === 'string' ? step.thinking : '',
      code: typeof step.code === 'string' ? step.code : null,
      final_answer: typeof step.final_answer === 'string' ? step.final_answer : null,
      is_final_answer: step.is_final_answer,
    }
  } catch {
    return {
      thinking: '',
      code: null,
      final_answer: content,
      is_final_answer: true,
    }
  }
}

export function parseToolOutput(content: string): string {
  try {
    const data: unknown = JSON.parse(content)
    if (data && typeof data === 'object' && 'output' in data) {
      const output = (data as { output?: unknown }).output
      return typeof output === 'string' ? output : content
    }
  } catch {
    // Unstructured tool output is valid display text.
  }
  return content
}

export function userDisplayText(content: string): string {
  return normalizeMessageContent(content)
}

export function traceOnlyStep(step: AgentStep): AgentStep | null {
  const hasThinking = Boolean(step.thinking?.trim())
  const hasCode = Boolean(step.code?.trim())
  if (!hasThinking && !hasCode) return null
  return {
    thinking: step.thinking,
    code: step.code ?? null,
    final_answer: null,
    is_final_answer: false,
  }
}

export function normalizeHistoryMessages(messages: Message[]): Message[] {
  return messages.flatMap((msg) => {
    if (msg.step_kind === 'user') {
      return [{ ...msg, content: userDisplayText(msg.content) }]
    }
    if (msg.step_kind !== 'assistant') return [msg]

    const step = parseAgentStep(msg.content)
    if (!step.is_final_answer) return [msg]

    const out: Message[] = []
    const trace = traceOnlyStep(step)
    if (trace) {
      out.push({
        ...msg,
        content: JSON.stringify(trace),
        message_id: msg.message_id ? `${msg.message_id}:trace` : undefined,
        artifact_ids: undefined,
      })
    }
    out.push({
      ...msg,
      content: JSON.stringify({
        thinking: '',
        code: null,
        final_answer: step.final_answer ?? step.thinking,
        is_final_answer: true,
      }),
      artifact_ids: msg.artifact_ids ?? [],
    })
    return out
  })
}

export function isTraceMessage(message: Message): boolean {
  if (message.step_kind === 'tool') return true
  return message.step_kind === 'assistant' && !parseAgentStep(message.content).is_final_answer
}
