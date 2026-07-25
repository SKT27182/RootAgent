import type { ArtifactItem, ChatResponsePayload } from '@/api'
import type { AgentStep } from '@/types'

interface EventEnvelope {
  type: string
  run_id: string
  session_id: string
}

export interface RunStartedEvent extends EventEnvelope {
  type: 'run_started'
  request_id: string
}

export interface StepEvent extends EventEnvelope {
  type: 'step'
  step_index: number
  step: AgentStep
}

export interface ToolEvent extends EventEnvelope {
  type: 'tool'
  step_index: number
  observation: string
}

export interface ArtifactEvent extends EventEnvelope {
  type: 'artifact'
  artifact: ArtifactItem
}

export interface DoneEvent extends EventEnvelope {
  type: 'done'
  request_id: string
  final_answer: string
  message_id: string
  generated_artifact_ids: string[]
}

export interface ErrorEvent {
  type: 'error'
  run_id: string | null
  session_id: string | null
  code: string
  message: string
  correlation_id: string
  retryable: boolean
}

export type ChatRunEvent =
  | RunStartedEvent
  | StepEvent
  | ToolEvent
  | ArtifactEvent
  | DoneEvent
  | ErrorEvent

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string')

export function isArtifactItem(value: unknown): value is ArtifactItem {
  if (!isRecord(value)) return false
  return (
    typeof value.id === 'string' &&
    (value.chat_id === undefined || typeof value.chat_id === 'string') &&
    typeof value.filename === 'string' &&
    typeof value.content_type === 'string' &&
    typeof value.file_size === 'number' &&
    (value.source === 'upload' || value.source === 'generated') &&
    (value.output_kind === null || ['png', 'csv', 'xlsx'].includes(String(value.output_kind))) &&
    typeof value.sha256 === 'string' &&
    typeof value.content_url === 'string' &&
    typeof value.download_url === 'string' &&
    (value.created_at === undefined || typeof value.created_at === 'string')
  )
}

function isAgentStep(value: unknown): value is AgentStep {
  if (!isRecord(value) || typeof value.is_final_answer !== 'boolean') return false
  return (
    typeof value.thinking === 'string' &&
    (value.code === undefined || value.code === null || typeof value.code === 'string') &&
    (value.final_answer === undefined ||
      value.final_answer === null ||
      typeof value.final_answer === 'string')
  )
}

export function parseChatRunEvent(raw: unknown): ChatRunEvent | null {
  if (!isRecord(raw)) return null
  if (raw.type === 'error') {
    return (raw.run_id === null || typeof raw.run_id === 'string') &&
      (raw.session_id === null || typeof raw.session_id === 'string') &&
      typeof raw.code === 'string' &&
      typeof raw.message === 'string' &&
      typeof raw.correlation_id === 'string' &&
      typeof raw.retryable === 'boolean'
      ? (raw as unknown as ErrorEvent)
      : null
  }
  if (typeof raw.type !== 'string' || typeof raw.run_id !== 'string' || typeof raw.session_id !== 'string') return null
  const envelope = raw as Record<string, unknown> & EventEnvelope
  switch (envelope.type) {
    case 'run_started':
      return typeof raw.request_id === 'string' ? (raw as unknown as RunStartedEvent) : null
    case 'step':
      return Number.isInteger(raw.step_index) && Number(raw.step_index) >= 0 && isAgentStep(raw.step)
        ? (raw as unknown as StepEvent)
        : null
    case 'tool': {
      const observation = raw.observation ?? raw.content
      return Number.isInteger(raw.step_index) && Number(raw.step_index) >= 0 && typeof observation === 'string'
        ? ({ ...raw, observation } as unknown as ToolEvent)
        : null
    }
    case 'artifact':
      return isArtifactItem(raw.artifact) ? (raw as unknown as ArtifactEvent) : null
    case 'done':
      return typeof raw.request_id === 'string' &&
        typeof raw.final_answer === 'string' &&
        typeof raw.message_id === 'string' &&
        isStringArray(raw.generated_artifact_ids)
        ? (raw as unknown as DoneEvent)
        : null
    default:
      return null
  }
}

export function responseToDone(response: ChatResponsePayload): DoneEvent {
  return {
    type: 'done',
    run_id: response.run_id,
    session_id: response.session_id,
    request_id: response.request_id,
    final_answer: response.final_answer ?? response.response ?? '',
    message_id: response.message_id ?? response.request_id,
    generated_artifact_ids: response.generated_artifact_ids,
  }
}
