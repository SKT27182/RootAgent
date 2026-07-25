export type StepKind = 'user' | 'assistant' | 'tool'

export interface AgentStep {
  thinking: string
  code?: string | null
  final_answer?: string | null
  is_final_answer: boolean
}

export interface Message {
  role: "user" | "assistant"
  content: string
  step_kind?: StepKind
  timestamp: string
  message_id?: string
  step_index?: number | null
  artifact_ids?: string[]
}

export interface ChatResponse {
  response: string
  session_id: string
  message_id: string
}
