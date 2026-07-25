/** Lightweight Python syntax highlighter for agent code blocks. */

const KEYWORDS = new Set([
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break',
  'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally',
  'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal',
  'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
])

const BUILTINS = new Set([
  'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'filter', 'float', 'format',
  'int', 'len', 'list', 'map', 'max', 'min', 'open', 'print', 'range', 'reversed',
  'set', 'sorted', 'str', 'sum', 'tuple', 'type', 'zip', 'Exception', 'ValueError',
  'TypeError', 'KeyError', 'IndexError', 'RuntimeError',
])

const TOKEN =
  /(#.*?$)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(\b[A-Za-z_][A-Za-z0-9_]*\b)|(\s+)|(.)/gm

export type HighlightSegment = {
  text: string
  className?: string
}

export function highlightPython(code: string): HighlightSegment[] {
  const segments: HighlightSegment[] = []
  let match: RegExpExecArray | null
  TOKEN.lastIndex = 0
  while ((match = TOKEN.exec(code)) !== null) {
    const [, comment, stringLiteral, number, ident, whitespace, other] = match
    if (comment) {
      segments.push({ text: comment, className: 'text-emerald-700 dark:text-emerald-400' })
    } else if (stringLiteral) {
      segments.push({ text: stringLiteral, className: 'text-amber-700 dark:text-amber-300' })
    } else if (number) {
      segments.push({ text: number, className: 'text-violet-700 dark:text-violet-300' })
    } else if (ident) {
      if (KEYWORDS.has(ident)) {
        segments.push({ text: ident, className: 'text-sky-700 dark:text-sky-300 font-semibold' })
      } else if (BUILTINS.has(ident)) {
        segments.push({ text: ident, className: 'text-cyan-700 dark:text-cyan-300' })
      } else {
        segments.push({ text: ident })
      }
    } else if (whitespace) {
      segments.push({ text: whitespace })
    } else if (other) {
      segments.push({ text: other, className: 'text-rose-700 dark:text-rose-300' })
    }
  }
  return segments
}
