import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Send,
  Loader2,
  Menu,
  Settings2,
  Paperclip,
  ImagePlus,
  X,
} from 'lucide-react'
import type { Message as MessageType } from '@/types'
import { ChatMessageBubble, shouldHideMessage } from '@/components/ChatMessageBubble'

interface ChatMainProps {
  scrollRef: React.RefObject<HTMLDivElement | null>
  messages: MessageType[]
  showReasoning: boolean
  isStreaming: boolean
  chatError: string
  input: string
  onInputChange: (v: string) => void
  onSend: () => void
  onKeyDown: (e: React.KeyboardEvent) => void
  csvFile: { name: string; content: string } | null
  onClearCsv: () => void
  images: { name: string; base64: string }[]
  onRemoveImage: (index: number) => void
  fileInputRef: React.RefObject<HTMLInputElement | null>
  imageInputRef: React.RefObject<HTMLInputElement | null>
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  onImageSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  onOpenLeftSidebar: () => void
  onOpenRightSidebar: () => void
}

export function ChatMain({
  scrollRef,
  messages,
  showReasoning,
  isStreaming,
  chatError,
  input,
  onInputChange,
  onSend,
  onKeyDown,
  csvFile,
  onClearCsv,
  images,
  onRemoveImage,
  fileInputRef,
  imageInputRef,
  onFileSelect,
  onImageSelect,
  onOpenLeftSidebar,
  onOpenRightSidebar,
}: ChatMainProps) {
  return (
    <div className="flex-1 flex flex-col relative min-h-0 w-full min-w-0">
      <div className="h-14 border-b border-border flex items-center justify-between px-4 bg-background shrink-0">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={onOpenLeftSidebar}
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
          <span className="font-semibold text-sm">Chat</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onOpenRightSidebar}
          aria-label="Open control panel"
        >
          <Settings2 className="h-5 w-5" />
        </Button>
      </div>

      {chatError && (
        <div className="mx-4 mt-2 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {chatError}
        </div>
      )}

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full w-full p-4">
          <div className="space-y-6 max-w-4xl mx-auto pb-20">
            {messages.map((msg, idx) => {
              if (shouldHideMessage(msg, showReasoning)) return null
              return (
                <ChatMessageBubble key={msg.message_id ?? idx} msg={msg} />
              )
            })}
            {isStreaming && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground px-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Agent is working...
              </div>
            )}
            <div ref={scrollRef} />
          </div>
        </ScrollArea>
      </div>

      <div className="p-4 border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 shrink-0">
        <div className="max-w-4xl mx-auto flex flex-col gap-2">
          {csvFile && (
            <div className="flex items-center gap-2 bg-muted p-2 rounded-md w-fit text-sm text-foreground">
              <span className="font-medium text-xs flex items-center gap-1">
                <Paperclip className="h-3 w-3" />
                {csvFile.name}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-4 w-4 hover:bg-destructive/10 hover:text-destructive"
                onClick={onClearCsv}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          )}
          {images.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {images.map((img, idx) => (
                <div key={idx} className="relative group">
                  <img
                    src={img.base64}
                    alt={img.name}
                    className="h-16 w-16 object-cover rounded-md border border-border"
                  />
                  <Button
                    variant="destructive"
                    size="icon"
                    className="h-4 w-4 absolute -top-1 -right-1 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => onRemoveImage(idx)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 w-full">
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              accept="*/*"
              onChange={onFileSelect}
            />
            <input
              type="file"
              ref={imageInputRef}
              className="hidden"
              accept="image/*"
              multiple
              onChange={onImageSelect}
            />
            <Button
              variant="outline"
              size="icon"
              className="h-[60px] w-[60px] shrink-0"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              title="Upload file"
            >
              <Paperclip className="h-5 w-5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-[60px] w-[60px] shrink-0"
              onClick={() => imageInputRef.current?.click()}
              disabled={isStreaming}
              title="Upload images"
            >
              <ImagePlus className="h-5 w-5" />
            </Button>
            <Textarea
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Type a message..."
              className="min-h-[60px] resize-none"
              disabled={isStreaming}
            />
            <Button
              onClick={onSend}
              disabled={
                (!input.trim() && !csvFile && images.length === 0) || isStreaming
              }
              className="h-[60px] w-[60px] shrink-0"
            >
              {isStreaming ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Send className="h-5 w-5" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
