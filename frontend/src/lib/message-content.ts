type ContentPart = {
  type?: string
  text?: string
  image_url?: { url?: string } | string
}

/** Turn stored LLM message JSON into display markdown/text. */
export function normalizeMessageContent(content: string): string {
  if (typeof content !== 'string') {
    return String(content)
  }

  const trimmed = content.trim()
  if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) {
    return content
  }

  try {
    const parsed: unknown = JSON.parse(trimmed)

    if (Array.isArray(parsed)) {
      return (parsed as ContentPart[])
        .map((part) => {
          if (part.type === 'text' && part.text) {
            return part.text
          }
          if (part.type === 'image_url') {
            const url =
              typeof part.image_url === 'string'
                ? part.image_url
                : part.image_url?.url
            return url ? `![Generated Image](${url})` : ''
          }
          return ''
        })
        .filter(Boolean)
        .join('\n\n')
    }

    if (
      parsed &&
      typeof parsed === 'object' &&
      'text' in parsed &&
      typeof (parsed as ContentPart).text === 'string'
    ) {
      return (parsed as ContentPart).text as string
    }
  } catch {
    // Keep original content when not valid JSON.
  }

  return content
}
