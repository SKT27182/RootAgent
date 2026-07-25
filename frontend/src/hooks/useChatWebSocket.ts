import { useCallback, useEffect, useRef } from 'react'
import {
  createWebSocketTicket,
  getChatRun,
  getChatWebSocketUrl,
  isNotFound,
  sendChatMessage,
  type ArtifactItem,
  type ChatRequestPayload,
  type ChatResponsePayload,
} from '@/api'
import {
  parseChatRunEvent,
  responseToDone,
  type DoneEvent,
  type ErrorEvent,
  type RunStartedEvent,
  type StepEvent,
  type ToolEvent,
} from '@/lib/chat-protocol'

const RECOVERY_POLL_MS = 1_000
const RECOVERY_ATTEMPTS = 30

interface ChatWebSocketHandlers {
  onRunStarted: (event: RunStartedEvent) => void
  onStep: (event: StepEvent) => void
  onTool: (event: ToolEvent) => void
  onArtifact: (artifact: ArtifactItem) => void
  onError: (event: ErrorEvent) => void
  onDone: (event: DoneEvent) => void
}

export function useChatWebSocket(handlers: ChatWebSocketHandlers) {
  const handlersRef = useRef(handlers)
  const wsRef = useRef<WebSocket | null>(null)
  const recoveryAbortRef = useRef<AbortController | null>(null)
  const runVersionRef = useRef(0)

  useEffect(() => {
    handlersRef.current = handlers
  }, [handlers])

  const close = useCallback(() => {
    runVersionRef.current += 1
    recoveryAbortRef.current?.abort()
    recoveryAbortRef.current = null
    const socket = wsRef.current
    wsRef.current = null
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
  }, [])

  useEffect(() => close, [close])

  const send = useCallback(
    async (payload: ChatRequestPayload) => {
      close()
      const version = runVersionRef.current
      let terminal = false
      let acknowledged = false
      let recoveryStarted = false
      let activeRunId: string | null = null
      let activeSessionId = payload.session_id

      const isCurrent = () => version === runVersionRef.current
      const complete = (event: DoneEvent) => {
        if (terminal || !isCurrent()) return
        terminal = true
        handlersRef.current.onDone(event)
        wsRef.current?.close()
        wsRef.current = null
      }
      const fail = (event: ErrorEvent) => {
        if (terminal || !isCurrent()) return
        terminal = true
        handlersRef.current.onError(event)
        wsRef.current?.close()
        wsRef.current = null
      }

      const acceptRun = (runId: string, sessionId: string) => {
        if (activeRunId && activeRunId !== runId) return false
        if (activeSessionId && activeSessionId !== sessionId) return false
        activeRunId = runId
        activeSessionId = sessionId
        return true
      }

      const emitRecovered = (response: ChatResponsePayload) => {
        if (!acceptRun(response.run_id, response.session_id)) return
        if (!acknowledged) {
          acknowledged = true
          handlersRef.current.onRunStarted({
            type: 'run_started',
            run_id: response.run_id,
            session_id: response.session_id,
            request_id: response.request_id,
          })
        }
        for (const artifact of response.artifacts ?? []) {
          handlersRef.current.onArtifact(artifact)
        }
        if (response.status === 'completed') complete(responseToDone(response))
        else if (response.status === 'failed') {
          fail({
            type: 'error',
            run_id: response.run_id,
            session_id: response.session_id,
            code: 'execution_failed',
            message: 'The chat run failed.',
            correlation_id: '',
            retryable: true,
          })
        }
      }

      const wait = (signal: AbortSignal) =>
        new Promise<void>((resolve, reject) => {
          const timer = window.setTimeout(resolve, RECOVERY_POLL_MS)
          signal.addEventListener(
            'abort',
            () => {
              window.clearTimeout(timer)
              reject(new DOMException('Aborted', 'AbortError'))
            },
            { once: true }
          )
        })

      const recover = async () => {
        if (recoveryStarted || terminal || acknowledged || !isCurrent()) return
        recoveryStarted = true
        const controller = new AbortController()
        recoveryAbortRef.current = controller
        try {
          let response: ChatResponsePayload
          try {
            response = await getChatRun(payload.request_id)
          } catch (error) {
            if (!isNotFound(error)) throw error
            response = await sendChatMessage(payload)
          }
          emitRecovered(response)
          for (
            let attempt = 0;
            (response.status === 'in_progress' || response.status === 'running') &&
            attempt < RECOVERY_ATTEMPTS;
            attempt += 1
          ) {
            await wait(controller.signal)
            response = await getChatRun(payload.request_id)
            emitRecovered(response)
          }
          if (!terminal && isCurrent()) {
            fail({
              type: 'error',
              run_id: response.run_id,
              session_id: response.session_id,
              code: 'run_recovery_timeout',
              message: 'The run is still processing. Reopen this chat to check its result.',
              correlation_id: '',
              retryable: true,
            })
          }
        } catch {
          if (controller.signal.aborted || !isCurrent()) return
          fail({
            type: 'error',
            run_id: activeRunId ?? '',
            session_id: activeSessionId ?? '',
            code: 'chat_unavailable',
            message: 'Unable to start or recover the chat run.',
            correlation_id: '',
            retryable: true,
          })
        } finally {
          if (recoveryAbortRef.current === controller) recoveryAbortRef.current = null
        }
      }

      let ticket: string
      try {
        ticket = await createWebSocketTicket()
      } catch {
        await recover()
        return
      }
      if (!isCurrent()) return

      const socket = new WebSocket(getChatWebSocketUrl(ticket))
      wsRef.current = socket
      socket.onopen = () => {
        if (isCurrent()) socket.send(JSON.stringify(payload))
      }
      socket.onmessage = (message) => {
        if (terminal || !isCurrent()) return
        let parsed: unknown
        try {
          parsed = JSON.parse(String(message.data))
        } catch {
          parsed = null
        }
        const event = parseChatRunEvent(parsed)
        if (!event) {
          acknowledged = true
          fail({
            type: 'error',
            run_id: activeRunId ?? '',
            session_id: activeSessionId ?? '',
            code: 'invalid_event',
            message: 'The server sent an invalid chat event.',
            correlation_id: '',
            retryable: false,
          })
          return
        }
        if (event.type === 'run_started' && event.request_id !== payload.request_id) return
        if (event.type === 'error') {
          if (event.run_id && activeRunId && event.run_id !== activeRunId) return
          if (event.session_id && activeSessionId && event.session_id !== activeSessionId) return
          acknowledged = true
          fail(event)
          return
        }
        if (!acceptRun(event.run_id, event.session_id)) return
        acknowledged = true
        switch (event.type) {
          case 'run_started':
            handlersRef.current.onRunStarted(event)
            break
          case 'step':
            handlersRef.current.onStep(event)
            break
          case 'tool':
            handlersRef.current.onTool(event)
            break
          case 'artifact':
            handlersRef.current.onArtifact(event.artifact)
            break
          case 'done':
            complete(event)
            break
        }
      }
      socket.onerror = () => {
        socket.close()
        if (!acknowledged) void recover()
      }
      socket.onclose = () => {
        if (wsRef.current === socket) wsRef.current = null
        if (!terminal && !acknowledged) void recover()
        else if (!terminal && acknowledged) {
          fail({
            type: 'error',
            run_id: activeRunId ?? '',
            session_id: activeSessionId ?? '',
            code: 'stream_interrupted',
            message: 'The chat stream was interrupted. Reopen this chat to recover the result.',
            correlation_id: '',
            retryable: true,
          })
        }
      }
    },
    [close]
  )

  return { send, close }
}
