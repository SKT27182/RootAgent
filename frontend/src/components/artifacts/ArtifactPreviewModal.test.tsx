import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ArtifactPreviewModal } from '@/components/artifacts/ArtifactPreviewModal'
import type { ArtifactItem } from '@/api'

const fetchArtifactPreview = vi.fn()
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, fetchArtifactPreview: (...args: unknown[]) => fetchArtifactPreview(...args) }
})

const artifact: ArtifactItem = {
  id: 'artifact-1',
  filename: 'report.csv',
  content_type: 'text/csv',
  file_size: 20,
  source: 'generated',
  output_kind: 'csv',
  sha256: 'a'.repeat(64),
  content_url: '/artifacts/session/artifact/content',
  download_url: '/artifacts/session/artifact/download',
  preview_url: '/artifacts/session/artifact/preview',
}

describe('ArtifactPreviewModal', () => {
  it('loads a tabular preview only after the modal is mounted', async () => {
    fetchArtifactPreview.mockResolvedValueOnce({
      kind: 'table',
      columns: ['name', 'value'],
      rows: [['Ada', 42]],
      sheet_names: null,
      selected_sheet: null,
      truncated: false,
    })
    render(<ArtifactPreviewModal artifact={artifact} onClose={vi.fn()} />)

    expect(screen.getByText('Loading preview…')).toBeInTheDocument()
    expect(await screen.findByText('Ada')).toBeInTheDocument()
    expect(fetchArtifactPreview).toHaveBeenCalledOnce()
  })

  it('revokes an image blob URL when closed or unmounted', async () => {
    fetchArtifactPreview.mockResolvedValueOnce(new Blob(['image'], { type: 'image/png' }))
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const view = render(
      <ArtifactPreviewModal
        artifact={{ ...artifact, filename: 'image.png', content_type: 'image/png' }}
        onClose={vi.fn()}
      />
    )
    await waitFor(() => expect(create).toHaveBeenCalledOnce())
    view.unmount()
    expect(revoke).toHaveBeenCalledWith('blob:preview')
  })
})
