'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { exactInterview, assertCandidateCalendar, assertCompletedInterview } = require('../../scripts/ats/interview-acceptance-assertions.cjs');

function fixture() {
  const plan = { interviewId: 'synthetic-interview', version: 1,
    participants: [{ actorRef: 'synthetic-assigned' }], criteria: [{ key: 'delivery' }] };
  const scorecard = { scorecardId: 'synthetic-scorecard', interviewId: plan.interviewId,
    actorRef: 'synthetic-assigned', policyVersion: 'structured-interview-v1',
    jobRelatednessConfirmed: true, recommendation: 'HOLD', summary: 'private summary',
    ratings: [{ criterionKey: 'delivery', rating: 3, evidence: 'private evidence' }] };
  const row = { ...plan, status: 'COMPLETED', version: 2, scorecards: [structuredClone(scorecard)],
    scheduleHistory: [{ version: 2, status: 'COMPLETED', reason: 'private reason' }] };
  const candidate = { interviewId: plan.interviewId, type: 'SCREENING',
    startsAt: '2026-09-14T07:00:00Z', endsAt: '2026-09-14T08:00:00Z', timeZone: 'Europe/Istanbul',
    mode: 'VIDEO', location: 'https://meet.example.test/synthetic', status: 'COMPLETED',
    updatedAt: '2026-09-13T18:00:00Z' };
  const check = () => assertCompletedInterview([row], plan, scorecard, 'private summary', 'private evidence', 'private reason');
  return { plan, scorecard, row, candidate, check };
}

test('assigned scorecard and exact completed revision persist', () => {
  const f = fixture();
  assert.equal(f.check(), f.row);
  assert.equal(assertCandidateCalendar([f.candidate], f.plan.interviewId, 'COMPLETED', ['private reason']), f.candidate);
});

for (const [name, mutate] of [
  ['wrong interview', f => { f.row.interviewId = 'another'; }],
  ['pending status', f => { f.row.status = 'SCHEDULED'; }],
  ['unassigned author', f => { f.scorecard.actorRef = 'unassigned'; }],
  ['unconfirmed policy', f => { f.scorecard.jobRelatednessConfirmed = false; }],
  ['wrong policy', f => { f.scorecard.policyVersion = 'other'; }],
  ['wrong recommendation', f => { f.scorecard.recommendation = 'ADVANCE'; }],
  ['lost scorecard', f => { f.row.scorecards = []; }],
  ['duplicate scorecard', f => { f.row.scorecards.push(f.row.scorecards[0]); }],
  ['changed stored evidence', f => { f.row.scorecards[0].ratings[0].evidence = 'changed'; }],
  ['missing criterion', f => { f.scorecard.ratings = []; }],
  ['wrong criterion', f => { f.scorecard.ratings[0].criterionKey = 'unknown'; }],
  ['stale version', f => { f.row.version = 1; }],
  ['missing history', f => { f.row.scheduleHistory = []; }],
  ['wrong history reason', f => { f.row.scheduleHistory[0].reason = 'other'; }],
]) test(`rejects ${name} without echoing private evidence`, () => {
  const f = fixture(); mutate(f);
  assert.throws(f.check, error => !error.message.includes('private') && /mismatch/.test(error.message));
});

test('JSON object field order is not a persistence difference', () => {
  const f = fixture();
  f.row.scorecards[0] = Object.fromEntries(Object.entries(f.row.scorecards[0]).reverse());
  f.check();
});

for (const [name, mutate] of [
  ['unknown internal field', row => { row.scheduleHistory = []; }],
  ['nested private field', row => { row.location = { actorRef: 'private' }; }],
  ['missing public field', row => { delete row.type; }],
  ['reason in public string', row => { row.location = 'private reason'; }],
  ['wrong status', row => { row.status = 'CANCELLED'; }],
]) test(`candidate calendar rejects ${name}`, () => {
  const f = fixture(); mutate(f.candidate);
  assert.throws(() => assertCandidateCalendar([f.candidate], f.plan.interviewId, 'COMPLETED', ['private reason']));
});

test('all calendar rows are checked, not only selected interview', () => {
  const f = fixture();
  assert.throws(() => assertCandidateCalendar([f.candidate, { ...f.candidate, interviewId: 'other', actorRef: 'private' }], f.plan.interviewId, 'COMPLETED'));
});

test('empty, duplicate and mismatched readbacks fail closed', () => {
  const f = fixture();
  for (const rows of [null, {}, [], [f.row, f.row], [{ ...f.row, interviewId: 'other' }]]) {
    assert.throws(() => exactInterview(rows, f.plan.interviewId, 'COMPLETED'));
  }
});
