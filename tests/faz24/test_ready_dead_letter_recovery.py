from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/faz24'))
import recover_test_ready_dead_letter as recovery


class ReviewedRecoveryTest(unittest.TestCase):
    def setup_case(self, **changes):
        settings = SimpleNamespace(ready_redis_stream='original-stream', analysis_spec_version='1')
        row = dict(state='DEAD', dead_reason='RETRY_EXHAUSTED',
                   last_error_code='processing_OllamaSchemaInvalidError', redrive_count=0,
                   dlq_published_at=1)
        row.update(changes)
        inbox = Mock()
        inbox._decrypt_event_metadata.return_value = ('event', 'original-sha', 'run-id', 'lookup')
        inbox.rearm_retry_exhausted_by_fingerprint.return_value = True
        fields = {b'payload': b'exact original producer bytes', b'eventType': b'meeting.transcript.ready'}
        broker = Mock()
        broker.xrange.side_effect = [[(b'1-0', fields)], []]
        parser = Mock(return_value=SimpleNamespace(lookup_key='lookup', payload_sha256='original-sha',
                                                  analysis_run_id='run-id'))
        return settings, row, inbox, fields, broker, parser

    def execute(self, case, apply=True):
        settings, row, inbox, _, broker, parser = case
        return recovery.recover(settings, inbox, broker, apply=apply, parse_event=parser,
                                read_row=lambda: row)

    def test_preflight_never_rearms_or_republishes(self):
        case = self.setup_case()
        self.assertEqual(self.execute(case, False)['status'], 'preflight-only')
        case[2].rearm_retry_exhausted_by_fingerprint.assert_not_called()
        case[4].xadd.assert_not_called()

    def test_apply_uses_canonical_audited_rearm_and_original_bytes(self):
        case = self.setup_case()
        self.assertEqual(self.execute(case)['status'], 'exact-original-event-republished')
        case[2].rearm_retry_exhausted_by_fingerprint.assert_called_once_with(
            recovery.FINGERPRINT, audit_reference=recovery.AUDIT)
        case[4].xadd.assert_called_once_with('original-stream', case[3])

    def test_missing_original_preserves_dead_row(self):
        case = self.setup_case()
        case[4].xrange.side_effect = [[]]
        with self.assertRaisesRegex(ValueError, 'not-retained'):
            self.execute(case)
        case[2].rearm_retry_exhausted_by_fingerprint.assert_not_called()

    def test_mismatched_payload_cannot_rearm(self):
        case = self.setup_case()
        case[5].return_value.payload_sha256 = 'changed'
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.execute(case)
        case[2].rearm_retry_exhausted_by_fingerprint.assert_not_called()

    def test_permanent_or_already_redriven_rows_cannot_rearm(self):
        for change in ({'dead_reason':'POISON'}, {'dead_reason':'CONFLICT'}, {'dead_reason':'TERMINAL'},
                       {'redrive_count':1}, {'state':'RECEIVED'}, {'dlq_published_at':None}):
            with self.subTest(change=change):
                case = self.setup_case(**change)
                with self.assertRaisesRegex(ValueError, 'state-changed'):
                    self.execute(case)
                case[2].rearm_retry_exhausted_by_fingerprint.assert_not_called()

    def test_canonical_rejection_cannot_publish(self):
        case = self.setup_case()
        case[2].rearm_retry_exhausted_by_fingerprint.return_value = False
        with self.assertRaisesRegex(ValueError, 'rearm-rejected'):
            self.execute(case)
        case[4].xadd.assert_not_called()

    def test_diagnosis_after_failed_redrive_never_rearms_or_publishes(self):
        settings, row, inbox, _, broker, parser = self.setup_case(redrive_count=1)
        diagnose = Mock(return_value={'outcome':'reproduced-error'})
        result = recovery.recover(settings, inbox, broker, apply=False, parse_event=parser,
                                  read_row=lambda:row, diagnose=diagnose)
        self.assertEqual(result['status'], 'diagnosed-without-rearm')
        inbox.rearm_retry_exhausted_by_fingerprint.assert_not_called()
        broker.xadd.assert_not_called()
        diagnose.assert_called_once_with(settings, parser.return_value)

    def test_diagnosis_cannot_mutate_even_if_apply_requested(self):
        settings, row, inbox, _, broker, parser = self.setup_case(redrive_count=1)
        with self.assertRaisesRegex(ValueError, 'diagnosis-cannot-rearm'):
            recovery.recover(settings, inbox, broker, apply=True, parse_event=parser,
                             read_row=lambda:row, diagnose=Mock())
        inbox.rearm_retry_exhausted_by_fingerprint.assert_not_called()

    def test_schema_diagnostic_excludes_input_messages_and_unknown_field_names(self):
        cause = Mock()
        cause.errors.return_value = [{'type':'int_type', 'loc':('action_item_sentences',0,'private-name'),
                                     'input':'SECRET', 'msg':'PRIVATE transcript'}]
        class DiagnosticCause(Exception):
            def errors(self, **kwargs):
                return cause.errors(**kwargs)
        error = ValueError('PRIVATE transcript')
        error.__cause__ = DiagnosticCause()
        result = recovery.safe_schema_error(error)
        self.assertEqual(result, {'errorClass':'ValueError',
            'validation':[{'type':'int_type','location':['action_item_sentences',0,'other']}]})
        cause.errors.assert_called_once_with(include_input=False, include_context=False, include_url=False)


if __name__ == '__main__':
    unittest.main()
