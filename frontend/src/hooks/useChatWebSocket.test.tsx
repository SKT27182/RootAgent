import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatWebSocket } from '@/hooks/useChatWebSocket'

const mocks = vi.hoisted(() => ({
  createTicket: vi.fn(),
  getRun: vi.fn(),
  sendChat: vi.fn(),
  isNotFound: vi.fn(),
}))

vi.mock('@/api', () => ({
  createWebSocketTicket: mocks.createTicket,
  getChatRun: mocks.getRun,
  getChatWebSocketUrl: (ticket: string) => `ws://localhost/chat/ws?ticket=${ticket}`,
  isNotFound: mocks.isNotFound,
  sendChatMessage: mocks.sendChat,
}))

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static readonly CLOSING = 2
  readonly url: string
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  send(value: string) { this.sent.push(value) }
  close() {
    if (this.readyState >= FakeWebSocket.CLOSING) return
    this.readyState = 3
    this.onclose?.()
  }
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent)
  }
  error() { this.onerror?.() }
}

function Harness() {
  const [started, setStarted] = useState(0)
  const [steps, setSteps] = useState(0)
  const [done, setDone] = useState(0)
  const [errors, setErrors] = useState(0)
  const { send } = useChatWebSocket({
    onRunStarted: () => setStarted((value) => value + 1),
    onStep: () => setSteps((value) => value + 1),
    onTool: () => undefined,
    onArtifact: () => undefined,
    onError: () => setErrors((value) => value + 1),
    onDone: () => setDone((value) => value + 1),
  })
  return (
    <div>
      <button
        onClick={() => void send({
          request_id: 'request-1',
          session_id: 'session-1',
          query: 'hello',
        })}
      >send</button>
      <output data-testid="started">{started}</output>
      <output data-testid="steps">{steps}</output>
      <output data-testid="done">{done}</output>
      <output data-testid="errors">{errors}</output>
    </div>
  )
}

describe('useChatWebSocket', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    mocks.createTicket.mockReset().mockResolvedValue('ticket-1')
    mocks.getRun.mockReset()
    mocks.sendChat.mockReset()
    mocks.isNotFound.mockReset()
  })

  it('stays connected until done and ignores events from another session', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'send' }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const socket = FakeWebSocket.instances[0]!
    act(() => socket.open())
    expect(JSON.parse(socket.sent[0]!)).toMatchObject({ request_id: 'request-1' })

    act(() => socket.message({
      type: 'run_started', run_id: 'run-1', session_id: 'session-1', request_id: 'request-1',
    }))
    act(() => socket.message({
      type: 'step', run_id: 'run-1', session_id: 'session-other', step_index: 0,
      step: { thinking: 'wrong stream', is_final_answer: false },
    }))
    act(() => socket.message({
      type: 'step', run_id: 'run-1', session_id: 'session-1', step_index: 0,
      step: { thinking: '', final_answer: 'not terminal', is_final_answer: true },
    }))
    expect(screen.getByTestId('started')).toHaveTextContent('1')
    expect(screen.getByTestId('steps')).toHaveTextContent('1')
    expect(screen.getByTestId('done')).toHaveTextContent('0')
    expect(socket.readyState).toBe(1)

    act(() => socket.message({
      type: 'done', run_id: 'run-1', session_id: 'session-1', request_id: 'request-1',
      final_answer: 'finished', message_id: 'message-1', generated_artifact_ids: [],
    }))
    expect(screen.getByTestId('done')).toHaveTextContent('1')
    expect(socket.readyState).toBe(3)
    expect(mocks.sendChat).not.toHaveBeenCalled()
  })

  it('runs at most one HTTP recovery when both error and close fire before acknowledgement', async () => {
    const missing = new Error('missing')
    mocks.getRun.mockRejectedValue(missing)
    mocks.isNotFound.mockReturnValue(true)
    mocks.sendChat.mockResolvedValue({
      run_id: 'run-1', request_id: 'request-1', session_id: 'session-1',
      final_answer: 'recovered', message_id: 'message-1', generated_artifact_ids: [], artifacts: [], status: 'completed',
    })
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'send' }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    act(() => FakeWebSocket.instances[0]!.error())
    await waitFor(() => expect(screen.getByTestId('done')).toHaveTextContent('1'))
    expect(mocks.getRun).toHaveBeenCalledTimes(1)
    expect(mocks.sendChat).toHaveBeenCalledTimes(1)
  })

  it('closes its socket on unmount without replaying the prompt', async () => {
    const user = userEvent.setup()
    const view = render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'send' }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const socket = FakeWebSocket.instances[0]!
    act(() => socket.open())
    view.unmount()
    expect(socket.readyState).toBe(3)
    expect(mocks.sendChat).not.toHaveBeenCalled()
  })
})
