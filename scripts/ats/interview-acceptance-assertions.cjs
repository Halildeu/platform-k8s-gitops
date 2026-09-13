'use strict';

const { isDeepStrictEqual } = require('node:util');

const candidateFields = new Set([
  'interviewId', 'type', 'startsAt', 'endsAt', 'timeZone', 'mode', 'location',
  'status', 'updatedAt',
]);

function exactInterview(rows, id, status) {
  if (!Array.isArray(rows) || typeof id !== 'string' || !id) {
    throw new Error('interview readback shape mismatch');
  }
  const matches = rows.filter(row => row?.interviewId === id);
  if (matches.length !== 1 || matches[0].status !== status) {
    throw new Error('interview readback identity/status mismatch');
  }
  return matches[0];
}

function assertCandidateCalendar(rows, id, status, privateValues = []) {
  const selected = exactInterview(rows, id, status);
  // An allowlist also rejects new internal fields and nested payloads, not just known keys.
  if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row) ||
      Object.keys(row).length !== candidateFields.size ||
      Object.entries(row).some(([key, value]) => !candidateFields.has(key) || typeof value !== 'string'))) {
    throw new Error('candidate calendar public contract mismatch');
  }
  const serialized = JSON.stringify(rows);
  if (privateValues.some(value => typeof value === 'string' && value && serialized.includes(value))) {
    throw new Error('candidate calendar private value leak');
  }
  return selected;
}

function assertCompletedInterview(rows, plan, scorecard, expectedSummary, expectedEvidence, reason) {
  const interview = exactInterview(rows, plan.interviewId, 'COMPLETED');
  const saved = interview.scorecards?.filter(row => row.scorecardId === scorecard.scorecardId);
  if (!scorecard.scorecardId || scorecard.interviewId !== plan.interviewId ||
      !plan.participants?.some(row => row.actorRef === scorecard.actorRef) ||
      scorecard.policyVersion !== 'structured-interview-v1' ||
      scorecard.jobRelatednessConfirmed !== true || scorecard.recommendation !== 'HOLD' ||
      scorecard.summary !== expectedSummary ||
      !Array.isArray(scorecard.ratings) || scorecard.ratings.length !== plan.criteria.length ||
      plan.criteria.some(criterion => scorecard.ratings.filter(rating =>
        rating.criterionKey === criterion.key && rating.rating === 3 &&
        rating.evidence === expectedEvidence).length !== 1) ||
      saved?.length !== 1 || !isDeepStrictEqual(saved[0], scorecard)) {
    throw new Error('assigned interview scorecard persistence mismatch');
  }
  if (!Number.isInteger(interview.version) || interview.version <= plan.version ||
      !interview.scheduleHistory?.some(row => row.version === interview.version &&
        row.status === 'COMPLETED' && row.reason === reason)) {
    throw new Error('interview completion revision/history mismatch');
  }
  return interview;
}

module.exports = { exactInterview, assertCandidateCalendar, assertCompletedInterview };
