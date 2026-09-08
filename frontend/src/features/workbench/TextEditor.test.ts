// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, it } from 'vitest'
import TextEditor from './TextEditor.vue'

afterEach(() => { cleanup(); localStorage.clear() })

it('locks a sentence, renders it green and allows unlocking it after moving', async () => {
  const view = render(TextEditor, { props: { modelValue: '保留这句。优化这句。', autosaveKey: 'draft-a', versionId: 'a' } })
  await fireEvent.click(screen.getByRole('button', { name: '锁定句子：保留这句。' }))
  expect(view.emitted().toggleSentence?.[0]).toEqual([expect.objectContaining({ text: '保留这句。', start: 0, end: 5, lockIds: [] })])
  const locks = [{ id: 'lock', text: '保留这句。', sourceVersionId: 'a', startOffset: 0, endOffset: 5 }]
  await view.rerender({ locks })
  expect(view.container.querySelector('.locked-sentence')?.textContent).toBe('保留这句。')
  await view.rerender({ modelValue: '新开头。保留这句。', autosaveKey: 'draft-b', versionId: 'b', locks })
  await fireEvent.click(screen.getByRole('button', { name: '取消保留：保留这句。' }))
  expect(view.emitted().toggleSentence?.[1]).toEqual([expect.objectContaining({ start: 4, end: 9, lockIds: ['lock'] })])
  await fireEvent.click(screen.getByRole('button', { name: '编辑' }))
  expect(screen.getByRole('textbox', { name: '成品文案编辑器' })).toBeTruthy()
})
