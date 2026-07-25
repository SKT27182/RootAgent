import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ArtifactItem } from '@/api'
import { ControlPanel } from '@/components/chat/ControlPanel'

vi.mock('@/components/artifacts/ArtifactPreviewModal', () => ({
  ArtifactPreviewModal: ({ artifact }: { artifact: ArtifactItem }) => <div>Previewing {artifact.filename}</div>,
}))

const artifact = (overrides: Partial<ArtifactItem>): ArtifactItem => ({
  id: 'artifact-1',
  chat_id: 'session-1',
  filename: 'input.csv',
  content_type: 'text/csv',
  file_size: 100,
  source: 'upload',
  output_kind: null,
  sha256: 'a'.repeat(64),
  content_url: '/artifacts/session-1/artifact-1/content',
  download_url: '/artifacts/session-1/artifact-1/download',
  created_at: new Date(0).toISOString(),
  ...overrides,
})

const renderPanel = (overrides: Partial<React.ComponentProps<typeof ControlPanel>> = {}) => {
  const props: React.ComponentProps<typeof ControlPanel> = {
    currentSessionId: 'session-1',
    artifacts: [],
    artifactStatus: 'idle',
    artifactOperationError: '',
    onArtifactUploadClick: vi.fn(),
    onDeleteArtifact: vi.fn(),
    onDownloadArtifact: vi.fn(),
    onRetryArtifacts: vi.fn(),
    onCopySessionId: vi.fn(),
    isStreaming: false,
    ...overrides,
  }
  return { ...render(<ControlPanel {...props} />), props }
}

describe('ControlPanel artifacts', () => {
  it('does not expose optional trace controls', () => {
    renderPanel()
    expect(screen.queryByText('Use reasoning')).not.toBeInTheDocument()
    expect(screen.queryByText('Show reasoning')).not.toBeInTheDocument()
  })

  it('shows unified uploaded/generated cards without automatic previews', () => {
    renderPanel({
      artifacts: [
        artifact({ id: 'upload', filename: 'input.csv' }),
        artifact({
          id: 'chart', filename: 'chart.png', content_type: 'image/png',
          source: 'generated', output_kind: 'png',
        }),
        artifact({
          id: 'table', filename: 'result.xlsx', source: 'generated', output_kind: 'xlsx',
        }),
      ],
    })
    expect(screen.getByText('Uploaded artifacts')).toBeInTheDocument()
    expect(screen.getByText('Generated artifacts')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'chart.png' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Preview/ })).toHaveLength(3)
    expect(screen.getAllByRole('button', { name: /Download/ })).toHaveLength(3)
    expect(screen.getAllByRole('button', { name: /Delete/ })).toHaveLength(3)
  })

  it('renders retry and operation error states independently', async () => {
    const retry = vi.fn()
    const user = userEvent.setup()
    renderPanel({
      artifactStatus: 'error',
      artifactOperationError: 'The file exceeds the 50 MiB upload limit.',
      onRetryArtifacts: retry,
    })
    expect(screen.getByRole('alert')).toHaveTextContent('50 MiB')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('keeps upload enabled on a new chat with no session id', () => {
    renderPanel({ currentSessionId: null })
    expect(screen.getByRole('button', { name: /Upload CSV or XLSX/i })).toBeEnabled()
  })

  it('disables upload while streaming', () => {
    renderPanel({ currentSessionId: null, isStreaming: true })
    expect(screen.getByRole('button', { name: /Upload CSV or XLSX/i })).toBeDisabled()
  })
})
