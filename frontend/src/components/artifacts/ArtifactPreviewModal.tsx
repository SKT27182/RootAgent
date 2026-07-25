import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import {
  fetchArtifactPreview,
  type ArtifactItem,
  type StructuredArtifactPreview,
} from '@/api'
import { Button } from '@/components/ui/button'

export function ArtifactPreviewModal({
  artifact,
  onClose,
}: {
  artifact: ArtifactItem
  onClose: () => void
}) {
  const [preview, setPreview] = useState<StructuredArtifactPreview | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null
    void fetchArtifactPreview(artifact, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result instanceof Blob) {
          objectUrl = URL.createObjectURL(result)
          setImageUrl(objectUrl)
        } else {
          setPreview(result)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('Could not load this preview.')
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [artifact, generation])

  const modalContent = (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 md:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={`Preview ${artifact.filename}`}
    >
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-border/80 bg-background shadow-2xl">
        <div className="flex items-center justify-between border-b border-border/40 px-5 py-3.5 bg-muted/20">
          <div className="min-w-0">
            <div className="truncate font-semibold text-sm text-foreground">{artifact.filename}</div>
            <div className="text-xs text-muted-foreground">{artifact.content_type}</div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close preview" className="h-8 w-8 rounded-lg">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="min-h-48 flex-1 overflow-auto p-5">
          {!preview && !imageUrl && !error && <p className="text-sm text-muted-foreground animate-pulse">Loading preview…</p>}
          {error && (
            <div className="space-y-3 text-sm">
              <p role="alert" className="text-destructive font-medium">{error}</p>
              <Button variant="outline" size="sm" className="rounded-xl" onClick={() => {
                setError('')
                setPreview(null)
                setImageUrl(null)
                setGeneration((value) => value + 1)
              }}>Retry</Button>
            </div>
          )}
          {imageUrl && <img src={imageUrl} alt={artifact.filename} className="mx-auto max-h-[75vh] max-w-full object-contain rounded-lg" />}
          {preview?.kind === 'table' && (
            <div className="space-y-3">
              {preview.sheet_names && <p className="text-xs font-medium text-muted-foreground">Sheet: {preview.selected_sheet}</p>}
              <div className="overflow-auto rounded-xl border border-border/50">
                <table className="min-w-full text-left text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr>{preview.columns.map((column) => <th key={column} className="border-b border-border/40 px-3 py-2 font-semibold text-muted-foreground">{column}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {preview.rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className="hover:bg-muted/30 transition-colors">{row.map((value, columnIndex) => <td key={columnIndex} className="px-3 py-2 text-foreground font-mono">{String(value ?? '')}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.truncated && <p className="text-xs text-muted-foreground">Preview limited to the first 100 rows.</p>}
            </div>
          )}
          {preview?.kind === 'text' && (
            <div className="space-y-3">
              {Object.keys(preview.metadata).length > 0 && <pre className="rounded-xl bg-muted/40 p-3 text-xs font-mono">{JSON.stringify(preview.metadata, null, 2)}</pre>}
              <pre className="whitespace-pre-wrap break-words rounded-xl border border-border/50 bg-card/40 p-4 text-xs font-mono leading-relaxed">{preview.text}</pre>
              {preview.truncated && <p className="text-xs text-muted-foreground">Preview limited to 200 KiB.</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  )

  return createPortal(modalContent, document.body)
}
