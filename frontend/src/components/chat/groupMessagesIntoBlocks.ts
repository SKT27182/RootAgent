import type { Message as MessageType } from '@/types'
import type { TraceStepPart } from '@/components/ChatMessageBubble'
import { parseAgentStep, parseToolOutput } from '@/lib/parse-history'

export type DisplayBlock =
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
