import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatMain } from '@/components/chat/ChatMain'
import { groupMessagesIntoBlocks } from '@/components/chat/groupMessagesIntoBlocks'
import type { Message } from '@/types'

const userMessage: Message = {
  message_id: 'user-1',
  role: 'user',
  step_kind: 'user',
  content: 'Analyze the table',
  timestamp: '2026-07-24T00:00:00Z',
}

const agentStep = (id: string, thinking: string, stepIndex = 0, code = 'print(1)'): Message => ({
  message_id: id,
  role: 'assistant',
  step_kind: 'assistant',
  content: JSON.stringify({
    thinking,
    code,
    final_answer: null,
    is_final_answer: false,
  }),
  timestamp: '2026-07-24T00:00:01Z',
  step_index: stepIndex,
})

const observation = (id: string, text: string, stepIndex = 0): Message => ({
  message_id: id,
  role: 'assistant',
  step_kind: 'tool',
  content: JSON.stringify({ output: text }),
  timestamp: '2026-07-24T00:00:02Z',
  step_index: stepIndex,
})

const baseProps = {
  scrollRef: { current: null },
  isStreaming: true,
  chatError: '',
  input: '',
  onInputChange: vi.fn(),
  onSend: vi.fn(),
  onKeyDown: vi.fn(),
  canUpload: false,
  onUploadClick: vi.fn(),
  onOpenLeftSidebar: vi.fn(),
  onOpenRightSidebar: vi.fn(),
}

describe('groupMessagesIntoBlocks', () => {
  it('groups consecutive agent/tool steps into one trace block', () => {
    const blocks = groupMessagesIntoBlocks([
      userMessage,
      agentStep('step-1', 'first', 0),
      observation('tool-1', 'Observation: 1', 0),
      agentStep('step-2', 'second', 1),
      observation('tool-2', 'Observation: 2', 1),
    ])

    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toMatchObject({ kind: 'user' })
    expect(blocks[1]).toMatchObject({ kind: 'trace_group' })
    if (blocks[1].kind === 'trace_group') {
      expect(blocks[1].parts).toHaveLength(2)
      expect(blocks[1].parts[0].observation).toBe('Observation: 1')
      expect(blocks[1].parts[1].observation).toBe('Observation: 2')
    }
  })
})

describe('ChatMain trace timeline', () => {
  it('collapses multi-step work into one box, expands while streaming, and allows manual expansion', async () => {
    const user = userEvent.setup()
    const view = render(
      <ChatMain
        {...baseProps}
        messages={[
          userMessage,
          agentStep('step-1', 'first', 0),
          observation('tool-1', 'Observation: 1', 0),
        ]}
      />
    )

    const working = screen.getByRole('button', { name: /Working · 1 step/i })
    expect(working).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Observation: 1')).toBeInTheDocument()
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy code' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Observation' })).not.toBeInTheDocument()

    view.rerender(
      <ChatMain
        {...baseProps}
        messages={[
          userMessage,
          agentStep('step-1', 'first', 0),
          observation('tool-1', 'Observation: 1', 0),
          agentStep('step-2', 'second', 1),
        ]}
      />
    )
    const multiStep = screen.getByRole('button', { name: /Working · 2 steps/i })
    expect(multiStep).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Step 1')).toBeInTheDocument()
    expect(screen.getByText('Step 2')).toBeInTheDocument()

    view.rerender(
      <ChatMain
        {...baseProps}
        isStreaming={false}
        messages={[
          userMessage,
          agentStep('step-1', 'first', 0),
          observation('tool-1', 'Observation: 1', 0),
          agentStep('step-2', 'second', 1),
        ]}
      />
    )
    const settled = screen.getByRole('button', { name: /Thought process · 2 steps/i })
    expect(settled).toHaveAttribute('aria-expanded', 'false')
    await user.click(settled)
    expect(settled).toHaveAttribute('aria-expanded', 'true')
  })

  it('renders the final answer without inline artifacts', () => {
    const finalMessage: Message = {
      message_id: 'final-1',
      role: 'assistant',
      step_kind: 'assistant',
      content: JSON.stringify({
        thinking: '',
        code: null,
        final_answer: 'Here is the chart.',
        is_final_answer: true,
      }),
      artifact_ids: ['chart-1'],
      timestamp: '2026-07-24T00:00:03Z',
    }

    render(
      <ChatMain
        {...baseProps}
        isStreaming={false}
        messages={[userMessage, finalMessage]}
      />
    )

    expect(screen.getByText('Here is the chart.')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
