import { describe, expect, it } from 'vitest'
import { parseChatRunEvent } from '@/lib/chat-protocol'

describe('chat run protocol', () => {
  it('rejects malformed and legacy terminal events', () => {
    expect(parseChatRunEvent({ type: 'done' })).toBeNull()
    expect(parseChatRunEvent({ type: 'info', session_id: 'session-1' })).toBeNull()
    expect(
      parseChatRunEvent({
        type: 'step',
        step_index: 0,
        run_id: 'run-1',
        session_id: 'session-1',
        step: { thinking: 'x', is_final_answer: 'yes' },
      })
    ).toBeNull()
  })

  it('normalizes a bounded tool observation field', () => {
    expect(
      parseChatRunEvent({
        type: 'tool',
        step_index: 0,
        run_id: 'run-1',
        session_id: 'session-1',
        content: 'rows: 10',
      })
    ).toMatchObject({ type: 'tool', observation: 'rows: 10' })
  })
})
