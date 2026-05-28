import type { ReactNode } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { cn } from '@/lib/utils'

interface ResizableShellProps {
  left: ReactNode
  main: ReactNode
  right?: ReactNode
  className?: string
}

export function ResizableShell({ left, main, right, className }: ResizableShellProps) {
  return (
    <Group
      orientation="horizontal"
      className={cn('h-full min-h-0 flex-1', className)}
      defaultLayout={
        right ? { left: 18, main: 52, right: 30 } : { left: 22, main: 78 }
      }
      id="rootagent-chat-panels"
    >
      <Panel id="left" defaultSize={22} minSize={14} maxSize={35}>
        {left}
      </Panel>
      <Separator className="w-1 bg-border hover:bg-primary/20 transition-colors" />
      <Panel id="main" minSize={35}>
        {main}
      </Panel>
      {right && (
        <>
          <Separator className="w-1 bg-border hover:bg-primary/20 transition-colors" />
          <Panel id="right" defaultSize={28} minSize={18} maxSize={40}>
            {right}
          </Panel>
        </>
      )}
    </Group>
  )
}
