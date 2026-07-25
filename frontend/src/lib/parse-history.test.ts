import { describe, expect, it } from 'vitest'
import {
  normalizeHistoryMessages,
  parseAgentStep,
  parseToolOutput,
  isTraceMessage,
  traceOnlyStep,
} from '@/lib/parse-history'

describe('history parsing', () => {
  it('renders malformed agent steps as a safe final answer', () => {
    expect(parseAgentStep('{not-json')).toEqual({
      thinking: '',
      code: null,
      final_answer: '{not-json',
      is_final_answer: true,
    })
  })

  it('renders malformed tool observations as plain text', () => {
    expect(parseToolOutput('<unstructured output>')).toBe('<unstructured output>')
  })

  it('splits persisted terminal steps into a trace card and final answer', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'final-1',
        role: 'assistant',
        step_kind: 'assistant',
        artifact_ids: ['artifact-1'],
        timestamp: '2026-07-24T00:00:00Z',
        content: JSON.stringify({
          thinking: 'I should inspect the table.',
          code: 'print(df.head())',
          final_answer: 'The table has five rows.',
          is_final_answer: true,
        }),
      },
    ])

    expect(normalized).toHaveLength(2)
    expect(normalized[0].message_id).toBe('final-1:trace')
    expect(parseAgentStep(normalized[0].content)).toMatchObject({
      thinking: 'I should inspect the table.',
      code: 'print(df.head())',
      final_answer: null,
      is_final_answer: false,
    })
    expect(isTraceMessage(normalized[0])).toBe(true)
    expect(normalized[0].artifact_ids).toBeUndefined()
    expect(parseAgentStep(normalized[1].content)).toMatchObject({
      thinking: '',
      code: null,
      final_answer: 'The table has five rows.',
      is_final_answer: true,
    })
    expect(normalized[1].artifact_ids).toEqual(['artifact-1'])
    expect(isTraceMessage(normalized[1])).toBe(false)
  })

  it('omits the trace card when a terminal step has no thinking or code', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'final-2',
        role: 'assistant',
        step_kind: 'assistant',
        timestamp: '2026-07-24T00:00:00Z',
        content: JSON.stringify({
          thinking: '   ',
          code: null,
          final_answer: 'Done.',
          is_final_answer: true,
        }),
      },
    ])

    expect(normalized).toHaveLength(1)
    expect(parseAgentStep(normalized[0].content)).toMatchObject({
      final_answer: 'Done.',
      is_final_answer: true,
    })
  })

  it('extracts only displayable trace content from a final step', () => {
    expect(
      traceOnlyStep({
        thinking: 'Trace',
        code: null,
        final_answer: 'Answer',
        is_final_answer: true,
      })
    ).toEqual({
      thinking: 'Trace',
      code: null,
      final_answer: null,
      is_final_answer: false,
    })
    expect(
      traceOnlyStep({
        thinking: '   ',
        code: null,
        final_answer: 'Answer',
        is_final_answer: true,
      })
    ).toBeNull()
  })
})
