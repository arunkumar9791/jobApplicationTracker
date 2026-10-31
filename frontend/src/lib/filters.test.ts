import { describe, expect, it } from 'vitest'
import { matchDatePreset, matchesSearch } from './filters'
import { addDays, daysBetween, describeFlag, formatDate } from './format'

describe('formatDate', () => {
  it('formats ISO dates day-first without timezone shifts', () => {
    expect(formatDate('2026-10-22')).toBe('22 Oct 2026')
    expect(formatDate('2026-01-01T00:30:00')).toBe('1 Jan 2026')
    expect(formatDate(null)).toBe('')
  })
})

describe('daysBetween', () => {
  it('counts calendar days', () => {
    expect(daysBetween('2026-10-22', '2026-10-31')).toBe(9)
    expect(daysBetween('2026-10-31', '2026-10-22')).toBe(-9)
  })
})

describe('matchDatePreset', () => {
  const today = '2026-10-31'
  it.each([
    ['2026-10-30', 'week', true],
    ['2026-10-24', 'week', false],
    ['2026-10-02', 'month', true],
    ['2026-10-30', 'overdue', true],
    ['2026-10-31', 'overdue', false],
    ['2026-11-07', 'upcoming', true],
    ['2026-11-08', 'upcoming', false],
    ['2027-10-23', 'future', true],
    [null, 'missing', true],
    [null, 'week', false],
  ] as const)('%s / %s -> %s', (value, preset, expected) => {
    expect(matchDatePreset(value, preset, today)).toBe(expected)
  })
})

describe('matchesSearch', () => {
  const rec = { company: 'Standard Chartered', title: null, notes: 'Referred by Priya' }
  it('matches case-insensitively across fields and ignores nulls', () => {
    expect(matchesSearch(rec, 'chartered', ['company', 'title'])).toBe(true)
    expect(matchesSearch(rec, 'priya', ['company', 'notes'])).toBe(true)
    expect(matchesSearch(rec, 'priya', ['company'])).toBe(false)
    expect(matchesSearch(rec, '  ', ['company'])).toBe(true)
  })
})

it('describes review flags', () => {
  expect(describeFlag('date_applied:future')).toBe('Date applied is in the future')
})

it('adds calendar days across month and year ends', () => {
  expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
  expect(addDays('2026-12-28', 6)).toBe('2027-01-03')
  expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
})
