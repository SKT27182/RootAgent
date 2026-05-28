import { useRef, useCallback } from 'react'
import { getChatWebSocketUrl, sendChatMessage, type ChatRequestPayload } from '@/api'
import type { Message as MessageType } from '@/types'

export function useChatWebSocket({
  onStep,
  onSessionId,
  onError,
  onDone,
}: {
  onStep: (msg: MessageType) => void
  onSessionId: (id: string) => void
  onError: (message: string) => void
  onDone: () => void
}) {
  const wsRef = useRef<WebSocket | null>(null)

  const close = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  const send = useCallback(
    async (payload: ChatRequestPayload) => {
      close()
      let completed = false

      const finish = () => {
        if (!completed) {
          completed = true
          onDone()
        }
      }

      const wsUrl = getChatWebSocketUrl()
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify(payload))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as {
          type: string
          session_id?: string
          step?: { is_final_answer?: boolean }
          content?: string
        }

        if (data.type === 'info' && data.session_id) {
          onSessionId(data.session_id)
        } else if (data.type === 'step' && data.step) {
          onStep({
            role: 'assistant',
            content: JSON.stringify(data.step),
            is_reasoning: !data.step.is_final_answer,
            step_kind: 'assistant',
            timestamp: new Date().toISOString(),
          })
          if (data.step.is_final_answer) {
            finish()
            ws.close()
          }
        } else if (data.type === 'tool') {
          onStep({
            role: 'assistant',
            content: JSON.stringify({ output: data.content }),
            is_reasoning: true,
            step_kind: 'tool',
            timestamp: new Date().toISOString(),
          })
        } else if (data.type === 'error') {
          onError(data.content || 'Agent error')
          finish()
          ws.close()
        }
      }

      ws.onerror = () => {
        if (!completed) {
          ws.close()
          void fallbackPost()
        }
      }

      ws.onclose = () => {
        if (!completed) {
          void fallbackPost()
        }
      }

      async function fallbackPost() {
        try {
          const res = await sendChatMessage(payload)
          if (res.session_id) {
            onSessionId(res.session_id)
          }
          onStep({
            role: 'assistant',
            content: JSON.stringify({
              thinking: '',
              final_answer: res.response,
              is_final_answer: true,
            }),
            is_reasoning: false,
            step_kind: 'assistant',
            timestamp: new Date().toISOString(),
          })
          finish()
        } catch (e: unknown) {
          const msg =
            e && typeof e === 'object' && 'response' in e
              ? (e as { response?: { data?: { detail?: string } } }).response?.data
                  ?.detail
              : null
          onError(msg || 'Failed to send message')
          finish()
        }
      }
    },
    [close, onStep, onSessionId, onError, onDone]
  )

  return { send, close }
}
