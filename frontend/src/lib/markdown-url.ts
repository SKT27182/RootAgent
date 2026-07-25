/** Keep Markdown links passive and limit application-relative URLs to artifacts. */
export function safeMarkdownUrl(uri: string): string {
  const candidate = uri.trim()
  if (!candidate) return ''

  if (candidate.startsWith('/artifacts/')) {
    try {
      const parsed = new URL(candidate, window.location.origin)
      if (parsed.origin === window.location.origin && parsed.pathname.startsWith('/artifacts/')) {
        return `${parsed.pathname}${parsed.search}${parsed.hash}`
      }
    } catch {
      return ''
    }
  }

  try {
    const parsed = new URL(candidate)
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? candidate : ''
  } catch {
    return ''
  }
}

export function isSameOriginArtifactUrl(uri: string): boolean {
  try {
    const parsed = new URL(uri, window.location.origin)
    return parsed.origin === window.location.origin && parsed.pathname.startsWith('/artifacts/')
  } catch {
    return false
  }
}
