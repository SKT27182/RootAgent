import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Copy, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ArtifactItem } from '@/api'
import { downloadArtifact } from '@/api'

interface ControlPanelProps {
  className?: string
  showCloseButton?: boolean
  onClose?: () => void
  useReasoning: boolean
  onUseReasoningChange: (v: boolean) => void
  showReasoning: boolean
  onShowReasoningChange: (v: boolean) => void
  currentSessionId: string | null
  artifacts: ArtifactItem[]
  selectedArtifactIds: string[]
  onSelectedArtifactIdsChange: (ids: string[]) => void
  onArtifactUploadClick: () => void
  onDeleteArtifact: (id: string) => void
  onCopySessionId: (id: string, e: React.MouseEvent) => void
  isStreaming: boolean
}

export function ControlPanel({
  className,
  showCloseButton,
  onClose,
  useReasoning,
  onUseReasoningChange,
  showReasoning,
  onShowReasoningChange,
  currentSessionId,
  artifacts,
  selectedArtifactIds,
  onSelectedArtifactIdsChange,
  onArtifactUploadClick,
  onDeleteArtifact,
  onCopySessionId,
  isStreaming,
}: ControlPanelProps) {
  return (
    <div
      className={cn(
        'border-l border-border bg-card flex flex-col h-full overflow-hidden',
        className
      )}
    >
      <div className="flex items-center justify-between p-4 border-b shrink-0">
        <h2 className="font-bold text-lg">Control Panel</h2>
        {showCloseButton && onClose && (
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="h-5 w-5" />
          </Button>
        )}
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-6">
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Reasoning</h3>
            <p className="text-xs text-muted-foreground">
              Manage how the AI thinks.
            </p>
          </div>

          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="use-reasoning" className="flex flex-col gap-0.5">
              <span className="text-sm">Use reasoning</span>
              <span className="font-normal text-xs text-muted-foreground">
                Chain-of-thought
              </span>
            </Label>
            <Switch
              id="use-reasoning"
              checked={useReasoning}
              onCheckedChange={onUseReasoningChange}
            />
          </div>

          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="show-reasoning" className="flex flex-col gap-0.5">
              <span className="text-sm">Show reasoning</span>
              <span className="font-normal text-xs text-muted-foreground">
                Display thinking steps
              </span>
            </Label>
            <Switch
              id="show-reasoning"
              checked={showReasoning}
              onCheckedChange={onShowReasoningChange}
            />
          </div>

          <Separator />

          <div className="space-y-2">
            <h3 className="text-sm font-medium">Artifacts</h3>
            <p className="text-xs text-muted-foreground">
              Files for this chat session.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              disabled={!currentSessionId}
              onClick={onArtifactUploadClick}
            >
              Upload file
            </Button>
            <ScrollArea className="h-40 rounded border border-border p-2">
              {artifacts.length === 0 ? (
                <p className="text-xs text-muted-foreground">No artifacts yet.</p>
              ) : (
                <ul className="space-y-2">
                  {artifacts.map((a) => (
                    <li
                      key={a.id}
                      className="text-xs border border-border rounded p-2 space-y-1"
                    >
                      <div className="font-medium truncate">{a.filename}</div>
                      <div className="flex flex-wrap gap-1">
                        {a.preview_url && (
                          <a
                            href={a.preview_url}
                            target="_blank"
                            rel="noreferrer"
                            className="underline text-primary"
                          >
                            Preview
                          </a>
                        )}
                        {currentSessionId && (
                          <button
                            type="button"
                            className="underline text-primary"
                            onClick={() =>
                              void downloadArtifact(
                                currentSessionId,
                                a.id,
                                a.filename
                              )
                            }
                          >
                            Download
                          </button>
                        )}
                        <button
                          type="button"
                          className="text-destructive underline"
                          onClick={() => onDeleteArtifact(a.id)}
                        >
                          Delete
                        </button>
                      </div>
                      <label className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={selectedArtifactIds.includes(a.id)}
                          disabled={isStreaming}
                          onChange={(e) => {
                            if (e.target.checked) {
                              onSelectedArtifactIdsChange([
                                ...selectedArtifactIds,
                                a.id,
                              ])
                            } else {
                              onSelectedArtifactIdsChange(
                                selectedArtifactIds.filter((id) => id !== a.id)
                              )
                            }
                          }}
                        />
                        Include in prompt
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </ScrollArea>
          </div>

          {currentSessionId && (
            <>
              <Separator />
              <div className="space-y-2">
                <h3 className="text-sm font-medium">Session ID</h3>
                <div className="p-2 bg-muted rounded text-xs font-mono break-all relative group text-foreground">
                  {currentSessionId}
                  <Button
                    variant="secondary"
                    size="icon"
                    className="h-5 w-5 absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={(e) => onCopySessionId(currentSessionId, e)}
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
  )
}
