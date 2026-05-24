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
  is_reasoning?: boolean
  step_kind?: StepKind
  timestamp: string
  message_id?: string
}

export interface ChatResponse {
  response: string
  session_id: string
  message_id: string
}

export interface ArtifactItem {
  id: string
  chat_id: string
  filename: string
  content_type: string
  file_size: number
  source: string
  created_at: string
  preview_url?: string | null
}
