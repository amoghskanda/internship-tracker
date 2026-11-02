import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applicationDate,
  parseApplicationRequest,
} from '../lib/application-fields.ts';

void test('rejects invalid JSON shapes, statuses, and field types', () => {
  for (const body of [
    null,
    [],
    'text',
    42,
    {},
    { id: 'x', status: 'Unknown' },
    { id: 'x', removed: 'false' },
    { id: 'x', notes: 'x'.repeat(4001) },
  ]) {
    assert.throws(() => parseApplicationRequest(body));
  }
});

void test('accepts real calendar dates and rejects rolled-over dates', () => {
  assert.equal(
    parseApplicationRequest({ id: 'x', interview_date: '2028-02-29' }).fields
      .interview_date,
    '2028-02-29',
  );
  for (const date of ['2027-02-29', '2027-04-31', '2027-13-01', 'tomorrow']) {
    assert.throws(() => parseApplicationRequest({ id: 'x', deadline: date }));
  }
});

void test('preserves explicit clears and false without accepting unrelated fields', () => {
  assert.deepEqual(
    parseApplicationRequest({
      id: ' x ',
      notes: '',
      manual_priority_override: '',
      removed: false,
      company: 'Ignored',
    }),
    {
      id: 'x',
      fields: { notes: '', manual_priority_override: '', removed: false },
    },
  );
});

void test('interested roles have no application date and applied roles retain theirs', () => {
  assert.equal(applicationDate('Interested', '2026-09-01', '2026-09-02'), '');
  assert.equal(applicationDate('Not applied', '2026-09-01', '2026-09-02'), '');
  assert.equal(applicationDate('Applied', '', '2026-09-02'), '2026-09-02');
  assert.equal(
    applicationDate('Interviewing', '2026-09-01', '2026-09-02'),
    '2026-09-01',
  );
});
