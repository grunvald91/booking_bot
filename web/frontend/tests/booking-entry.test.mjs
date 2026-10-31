import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Изолированная проверка фактического TS-хелпера без браузера и React.
const source = readFileSync(new URL('../src/pages/client/bookingEntry.ts', import.meta.url), 'utf8')
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText
const { resolveBookingEntry } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`)

const s1 = { id: 11, name: 'Диагностика', is_active: true }
const s2 = { id: 12, name: 'Ремонт', is_active: true }
const m1 = { id: 21, name: 'Анна', service_ids: [11] }
const m2 = { id: 22, name: 'Борис', service_ids: [11, 12] }
const business = (services = [s1, s2], employees = [m1, m2], options = {}) => ({
  id: 1, name: 'Тест', services, employees, ...options,
})

test('обычная ссылка на запись сохраняет начальную страницу', () => {
  const result = resolveBookingEntry(business(), null, null)
  assert.equal(result.step, 'home')
  assert.deepEqual(result.services, [])
  assert.equal(result.resource, null)
})

test('выбранная услуга сразу ведёт к выбору подходящего мастера', () => {
  const result = resolveBookingEntry(business(), 11, null)
  assert.equal(result.step, 'resource')
  assert.equal(result.services[0].id, 11)
  assert.equal(result.resource, null)
})

test('выбранная услуга и единственный подходящий мастер ведут к календарю', () => {
  const result = resolveBookingEntry(business(), 12, null)
  assert.equal(result.step, 'calendar')
  assert.equal(result.services[0].id, 12)
  assert.equal(result.resource.id, 22)
})

test('выбранный мастер ведёт к списку его услуг', () => {
  const result = resolveBookingEntry(business(), null, 22)
  assert.equal(result.step, 'services')
  assert.equal(result.resource.id, 22)
  assert.deepEqual(result.services, [])
})

test('для мастера с единственной доступной услугой сразу показываем календарь', () => {
  const result = resolveBookingEntry(business(), null, 21)
  assert.equal(result.step, 'calendar')
  assert.equal(result.services[0].id, 11)
  assert.equal(result.resource.id, 21)
})

test('готовая совместимая пара услуга и мастер переходит к календарю', () => {
  const result = resolveBookingEntry(business(), 11, 21)
  assert.equal(result.step, 'calendar')
  assert.equal(result.services[0].id, 11)
  assert.equal(result.resource.id, 21)
})

test('несовместимую пару нельзя сохранить: явную услугу оставляем', () => {
  const result = resolveBookingEntry(business(), 12, 21)
  assert.equal(result.step, 'calendar')
  assert.equal(result.services[0].id, 12)
  assert.equal(result.resource.id, 22)
})

test('устаревшая или дополнительная услуга не становится выбранной', () => {
  const list = [s1, { ...s2, is_active: false }, { id: 13, is_active: true, is_additional: true }]
  for (const id of [12, 13, 999]) {
    const result = resolveBookingEntry(business(list), id, null)
    assert.equal(result.step, 'services')
    assert.deepEqual(result.services, [])
  }
})

test('при отсутствии мастеров после выбранной услуги открываем календарь', () => {
  assert.equal(resolveBookingEntry(business([s1], []), 11, null).step, 'calendar')
})

test('аренда зала не пропускает выбор зала', () => {
  const room = { id: 31, name: 'Зал', service_ids: [] }
  const result = resolveBookingEntry(business([s1], [room], { business_type: 'venue_rental' }), 11, null)
  assert.equal(result.step, 'resource')
  assert.equal(result.resource, null)
})

test('настройка resource_first не теряет уже выбранную услугу', () => {
  const result = resolveBookingEntry(business([s1, s2], [m1, m2], { booking_flow_order: 'resource_first' }), 11, null)
  assert.equal(result.step, 'resource')
  assert.equal(result.services[0].id, 11)
})
