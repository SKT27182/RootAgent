import { describe, expect, it } from 'vitest'
import { highlightPython } from '@/lib/python-highlight'

describe('highlightPython', () => {
  it('marks keywords, strings, comments, and numbers', () => {
    const segments = highlightPython('def foo(x=1):\n  # note\n  return "bar"')
    const joined = segments.map((segment) => segment.text).join('')
    expect(joined).toBe('def foo(x=1):\n  # note\n  return "bar"')
    expect(segments.some((segment) => segment.text === 'def' && segment.className)).toBe(true)
    expect(segments.some((segment) => segment.text === '"bar"' && segment.className)).toBe(true)
    expect(segments.some((segment) => segment.text === '# note' && segment.className)).toBe(true)
    expect(segments.some((segment) => segment.text === '1' && segment.className)).toBe(true)
  })
})
