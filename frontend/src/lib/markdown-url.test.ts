import { describe, expect, it } from 'vitest'
import { safeMarkdownUrl } from '@/lib/markdown-url'

describe('safeMarkdownUrl', () => {
  it.each([
    'https://example.com/report.csv',
    'http://example.com',
    'mailto:analyst@example.com',
    '/artifacts/3c95/content',
  ])('allows %s', (url) => {
    expect(safeMarkdownUrl(url)).toBe(url)
  })

  it.each([
    'javascript:alert(1)',
    'data:image/svg+xml,<svg/>',
    'data:image/png;base64,AAAA',
    '/admin/users',
    '//evil.example/artifacts/3c95/content',
  ])('rejects %s', (url) => {
    expect(safeMarkdownUrl(url)).toBe('')
  })
})
