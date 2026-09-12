// @vitest-environment jsdom

import { beforeEach, expect, it } from 'vitest'
import { consumeReturnTo, safeReturnTo, saveReturnTo } from './returnTo'

beforeEach(() => sessionStorage.clear())

it('accepts only internal return routes and consumes them once', () => {
  expect(safeReturnTo('https://example.com')).toBe('/tasks')
  expect(safeReturnTo('//example.com')).toBe('/tasks')
  saveReturnTo('/workbench/task?tab=suggestions')
  expect(consumeReturnTo()).toBe('/workbench/task?tab=suggestions')
  expect(consumeReturnTo()).toBe('/tasks')
})
