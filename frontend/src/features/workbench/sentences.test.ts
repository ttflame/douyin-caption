import { expect, it } from 'vitest'
import { locateLocks, sentenceSelections } from './sentences'

it('segments Chinese sentences with punctuation and preserves whitespace', () => {
  const text = '  第一段。第二句！\n\n“第三句？”\n'
  const sentences = sentenceSelections(text, [])
  expect(sentences.filter(item => item.text).map(item => item.text)).toEqual(['第一段。', '第二句！', '“第三句？”'])
  expect(sentences.map(item => item.leading + item.text + item.trailing).join('')).toBe(text)
})

it('sends code-point offsets after emoji and keeps decimal numbers in a sentence', () => {
  const text = '🙂价格是3.14元。下一句。'
  const sentences = sentenceSelections(text, [])
  expect(sentences[0]?.text).toBe('🙂价格是3.14元。')
  for (const sentence of sentences) expect(Array.from(text).slice(sentence.start, sentence.end).join('')).toBe(sentence.text)
})

it('tracks repeated locked sentences separately and finds them after reordering', () => {
  const locks = [
    { id: 'second', text: '重复。', sourceVersionId: 'old', startOffset: 6, endOffset: 9 },
    { id: 'first', text: '开头。', sourceVersionId: 'old', startOffset: 0, endOffset: 3 },
  ]
  const old = sentenceSelections('开头。重复。重复。', locks, 'old')
  expect(old[1]?.lockIds).toEqual([])
  expect(old[2]?.lockIds).toEqual(['second'])
  const next = sentenceSelections('重复。新句子。开头。', locks, 'new')
  expect(next[0]?.lockIds).toEqual(['second'])
  expect(next[2]?.lockIds).toEqual(['first'])
  expect(locateLocks('重复。', [{ id: 'a', text: '重复。' }, { id: 'b', text: '重复。' }])).toHaveLength(1)
})

it('marks only the preserved substring of a legacy partial lock', () => {
  const sentence = sentenceSelections('这段必须保留。', [{ id: 'old', text: '必须保留' }])[0]!
  expect(sentence.parts.filter(part => part.locked).map(part => part.text)).toEqual(['必须保留'])
  expect(sentence.lockIds).toEqual(['old'])
})
