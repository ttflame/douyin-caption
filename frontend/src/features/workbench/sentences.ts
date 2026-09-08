import type { TextLock } from '../../shared/types'

export interface TextRange { start: number; end: number }
export interface SentenceSelection extends TextRange { text: string; lockIds: string[] }

export const codePointOffset = (text: string, utf16Offset: number) => Array.from(text.slice(0, utf16Offset)).length
const utf16Offset = (text: string, pointOffset: number) => Array.from(text).slice(0, pointOffset).join('').length

export function locateLocks(text: string, locks: TextLock[], versionId?: string) {
  const ranges: (TextRange & { id: string })[] = []
  for (const lock of [...locks].sort((a, b) => Number(b.sourceVersionId === versionId) - Number(a.sourceVersionId === versionId))) {
    let start = -1
    if (lock.sourceVersionId === versionId && lock.startOffset !== undefined && lock.endOffset !== undefined) {
      const offset = utf16Offset(text, lock.startOffset)
      if (text.slice(offset, utf16Offset(text, lock.endOffset)) === lock.text) start = offset
    }
    const occupied = (position: number) => ranges.some(range => position < range.end && position + lock.text.length > range.start)
    if (start < 0 || occupied(start)) {
      start = text.indexOf(lock.text)
      while (start >= 0 && occupied(start)) start = text.indexOf(lock.text, start + 1)
    }
    if (start >= 0) ranges.push({ id: lock.id, start, end: start + lock.text.length })
  }
  return ranges
}

export function sentenceSelections(text: string, locks: TextLock[], versionId?: string) {
  const ranges = locateLocks(text, locks, versionId)
  const segmenter = new Intl.Segmenter('zh', { granularity: 'sentence' })
  return Array.from(segmenter.segment(text), ({ segment, index }) => {
    const leading = segment.slice(0, segment.length - segment.trimStart().length)
    const trailing = segment.trim() ? segment.slice(segment.trimEnd().length) : ''
    const sentence = segment.trim()
    const start = index + leading.length
    const end = start + sentence.length
    const overlaps = ranges.filter(range => range.start < end && range.end > start)
    const boundaries = [...new Set([start, end, ...overlaps.flatMap(range => [Math.max(start, range.start), Math.min(end, range.end)])])].sort((a, b) => a - b)
    const parts = boundaries.slice(0, -1).map((point, i) => ({
      text: text.slice(point, boundaries[i + 1]),
      locked: overlaps.some(range => range.start <= point && range.end >= boundaries[i + 1]!),
    }))
    return { text: sentence, start: codePointOffset(text, start), end: codePointOffset(text, end), leading, trailing, parts, lockIds: overlaps.map(range => range.id) }
  })
}
