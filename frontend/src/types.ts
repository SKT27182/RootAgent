export interface Message {
  role: "user" | "assistant";
  content: string;
  is_reasoning?: boolean;
  timestamp: string;
  message_id?: string;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  message_id: string;
}
