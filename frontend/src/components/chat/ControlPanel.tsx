import { Copy, Download, Eye, File, FileUp, RefreshCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { ArtifactPreviewModal } from '@/components/artifacts/ArtifactPreviewModal'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import type { ArtifactItem } from '@/api'
import { cn } from '@/lib/utils'

interface ControlPanelProps {
  className?: string
  showCloseButton?: boolean
  onClose?: () => void
  currentSessionId: string | null
  artifacts: ArtifactItem[]
  artifactStatus: 'idle' | 'loading' | 'error'
  artifactOperationError: string
  onArtifactUploadClick: () => void
  onDeleteArtifact: (artifact: ArtifactItem) => void
  onDownloadArtifact: (artifact: ArtifactItem) => void
  onRetryArtifacts: () => void
  onCopySessionId: (id: string, event: React.MouseEvent) => void
  isStreaming: boolean
}

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

function ArtifactCard({
  artifact,
  isStreaming,
  onPreview,
  onDownload,
  onDelete,
}: {
  artifact: ArtifactItem
  isStreaming: boolean
  onPreview: () => void
  onDownload: () => void
  onDelete: () => void
}) {
  return (
    <li className="space-y-2.5 rounded-xl border border-border/50 bg-card/60 p-3 text-xs shadow-sm hover:border-primary/30 transition-all">
      <div className="flex items-start gap-2.5">
        <div className="p-1.5 rounded-lg bg-primary/10 text-primary shrink-0 mt-0.5">
          <File className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-foreground" title={artifact.filename}>
            {artifact.filename}
          </div>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {artifact.source === 'upload' ? 'Uploaded' : 'Generated'} · {artifact.content_type} · {formatBytes(artifact.file_size)}
          </div>
          {artifact.created_at && (
            <div className="text-[10px] text-muted-foreground/70 mt-0.5">
              {new Date(artifact.created_at).toLocaleString()}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1 pt-1 border-t border-border/30">
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2.5 text-[11px] rounded-lg hover:bg-muted" onClick={onPreview}>
          <Eye className="mr-1 h-3 w-3" /> Preview
        </Button>
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2.5 text-[11px] rounded-lg hover:bg-muted" onClick={onDownload}>
          <Download className="mr-1 h-3 w-3" /> Download
        </Button>
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2.5 text-[11px] rounded-lg text-destructive hover:text-destructive hover:bg-destructive/10" disabled={isStreaming} onClick={onDelete}>
          <Trash2 className="mr-1 h-3 w-3" /> Delete
        </Button>
      </div>
    </li>
  )
}

function EmptySection({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-dashed border-border/60 p-3.5 text-center text-xs text-muted-foreground/70">{children}</p>
}

export function ControlPanel({
  className,
  showCloseButton,
  onClose,
  currentSessionId,
  artifacts,
  artifactStatus,
  artifactOperationError,
  onArtifactUploadClick,
  onDeleteArtifact,
  onDownloadArtifact,
  onRetryArtifacts,
  onCopySessionId,
  isStreaming,
}: ControlPanelProps) {
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactItem | null>(null)
  const uploads = artifacts.filter((artifact) => artifact.source === 'upload')
  const generated = artifacts.filter((artifact) => artifact.source === 'generated')

  const section = (heading: string, empty: string, items: ArtifactItem[]) => (
    <section className="space-y-2.5" aria-label={heading}>
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">{heading}</h4>
      {items.length === 0 ? <EmptySection>{empty}</EmptySection> : (
        <ul className="space-y-2">
          {items.map((artifact) => (
            <ArtifactCard
              key={artifact.id}
              artifact={artifact}
              isStreaming={isStreaming}
              onPreview={() => setPreviewArtifact(artifact)}
              onDownload={() => onDownloadArtifact(artifact)}
              onDelete={() => {
                if (previewArtifact?.id === artifact.id) setPreviewArtifact(null)
                onDeleteArtifact(artifact)
              }}
            />
          ))}
        </ul>
      )}
    </section>
  )

  return (
    <>
      <div className={cn('flex h-full flex-col overflow-hidden border-l border-border/40 bg-card/60 backdrop-blur select-none', className)}>
        <div className="flex shrink-0 items-center justify-between border-b border-border/40 p-4">
          <h2 className="text-base font-bold tracking-tight">Artifacts</h2>
          {showCloseButton && onClose && <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={onClose} aria-label="Close control panel"><X className="h-4 w-4" /></Button>}
        </div>
        <ScrollArea className="flex-1 p-4">
          <div className="space-y-6 pb-4">
            <div className="space-y-3.5" aria-busy={artifactStatus === 'loading'}>
              <p className="text-xs text-muted-foreground">Files belonging only to this chat.</p>
              <Button
                variant="outline"
                size="sm"
                className="w-full rounded-xl border-border/60 bg-muted/30 hover:bg-muted hover:border-primary/40 font-medium h-9 text-xs transition-all"
                disabled={isStreaming}
                onClick={onArtifactUploadClick}
              >
                <FileUp className="mr-2 h-3.5 w-3.5 text-primary" /> Upload CSV or XLSX
              </Button>
              {artifactOperationError && <p role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 p-2.5 text-xs text-destructive">{artifactOperationError}</p>}
              {artifactStatus === 'loading' && <p className="text-xs text-muted-foreground animate-pulse">Loading artifacts…</p>}
              {artifactStatus === 'error' && (
                <div className="rounded-xl border border-destructive/40 p-3 text-xs space-y-2">
                  <p className="text-destructive">Could not load artifacts.</p>
                  <Button variant="ghost" size="sm" className="h-7 text-xs rounded-lg" disabled={isStreaming} onClick={onRetryArtifacts}><RefreshCw className="mr-1 h-3 w-3" /> Retry</Button>
                </div>
              )}
              {artifactStatus !== 'error' && (
                <>
                  {section('Uploaded artifacts', 'No uploaded artifacts.', uploads)}
                  {section('Generated artifacts', 'No generated artifacts.', generated)}
                </>
              )}
            </div>
            {currentSessionId && (
              <>
                <Separator className="opacity-40" />
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">Session ID</h3>
                  <div className="group relative flex items-center justify-between gap-1.5 rounded-xl border border-border/40 bg-muted/30 p-2.5 font-mono text-[11px] text-foreground w-full overflow-hidden">
                    <span className="w-0 flex-1 truncate select-all" title={currentSessionId}>{currentSessionId}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 rounded-lg shrink-0 text-muted-foreground hover:text-foreground hover:bg-background"
                      onClick={(event) => onCopySessionId(currentSessionId, event)}
                      title="Copy Session ID"
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </div>
      {previewArtifact && <ArtifactPreviewModal key={previewArtifact.id} artifact={previewArtifact} onClose={() => setPreviewArtifact(null)} />}
    </>
  )
}
