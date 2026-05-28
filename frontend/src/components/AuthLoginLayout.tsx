import type { ReactNode } from 'react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface AuthLoginLayoutProps {
  productName: string
  tagline: string
  icon: ReactNode
  children: ReactNode
}

export function AuthLoginLayout({
  productName,
  tagline,
  icon,
  children,
}: AuthLoginLayoutProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="p-3 rounded-xl bg-primary/10 text-primary">{icon}</div>
          <div>
            <h1 className="text-3xl font-bold">{productName}</h1>
            <p className="text-sm text-muted-foreground">{tagline}</p>
          </div>
        </div>
        <Card className={cn('shadow-sm')}>{children}</Card>
      </div>
    </div>
  )
}

export function AuthLoginCardHeader({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <CardHeader className="text-center">
      <CardTitle>{title}</CardTitle>
      <CardDescription>{description}</CardDescription>
    </CardHeader>
  )
}

export { CardContent }
