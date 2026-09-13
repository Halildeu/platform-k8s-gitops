"""Offline metric and pinned synthetic fixture tests; no external audio call."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'scripts/faz24/fixtures/meeting-speaker-tr-v1'
spec = importlib.util.spec_from_file_location('speaker_quality', ROOT / 'scripts/faz24/meeting-speaker-quality-run.py')
quality = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {'QUALITY_FIXTURES': str(FIXTURE), 'QUALITY_REPO': str(ROOT)}):
    spec.loader.exec_module(quality)


class SpeakerQualityTest(unittest.TestCase):
    def run_wrapper(self, attributed, stored, finals=112):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / 'token'
            token.write_text('synthetic-unit-test-not-a-credential')
            token.chmod(0o600)
            output = root / 'acceptance.json'
            data = {'sessionFinished': True, 'metrics': {'drained': True, 'eofAck': True,
                'errors': 0, 'finalEvents': finals}, 'durable': {'usableProductResult': True,
                'canonicalSourceReadBackProven': True, 'sameResultReopened': True},
                'speakerAttributedFinals': attributed, 'storedAttributedSegments': stored,
                'speakerMetadataExactReopen': True, 'speakerMetadataExactStreamToStore': True,
                'wer': 0, 'syntheticDER': {'diarization error rate': 0.05}}
            def fake_runner(*args, **kwargs):
                Path(os.environ['QUALITY_REPORT']).write_text(json.dumps(data))
            argv = ['wrapper', '--token-file', str(token), '--audio-file', str(FIXTURE / 'two-speaker-tr.wav'),
                '--output-file', str(output), '--base-url', 'https://testai.acik.com']
            wrapper = ROOT / 'scripts/faz24/meeting-speaker-quality-wrapper.py'
            with patch.dict(os.environ, {'QUALITY_PHASE': 'after', 'QUALITY_FIXTURES': str(FIXTURE), 'QUALITY_BROWSER_WAIT': ''}), \
                 patch('sys.argv', argv), patch('sys.stdin'), patch('runpy.run_path', side_effect=fake_runner):
                try:
                    exec(compile(wrapper.read_text(), str(wrapper), 'exec'), {'__name__': '__main__', '__file__': str(wrapper)})
                except SystemExit as error:
                    self.assertEqual(error.code, 1)
            return json.loads(output.read_text())

    def test_complete_attribution_passes_synthetic_api_gate(self):
        self.assertEqual(self.run_wrapper(112, 112)['status'], 'pass')

    def test_partial_attribution_fails_even_with_low_der(self):
        report = self.run_wrapper(111, 111)
        self.assertEqual(report['status'], 'fail')
        self.assertFalse(report['gates']['speakerFinals'])
        self.assertFalse(report['gates']['speakerStored'])

    def test_zero_final_events_cannot_pass_coverage_gate(self):
        self.assertEqual(self.run_wrapper(0, 0, 0)['status'], 'fail')

    def test_pinned_fixture_and_reference(self):
        audio = FIXTURE / 'two-speaker-tr.wav'
        reference = json.loads((FIXTURE / 'reference.json').read_text())
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), quality.EXPECTED)
        self.assertEqual(reference['sha256'], quality.EXPECTED)
        self.assertEqual(reference['kind'], 'synthetic-TTS-not-real-meeting')
        self.assertEqual(quality.validate_fixture(), reference)
        self.assertEqual(len(quality.normalized(' '.join(t['text'] for t in reference['turns'])).split()), 113)
        with wave.open(str(audio), 'rb') as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
            self.assertEqual(wav.getnframes()/16000, reference['durationSeconds'])

    def test_turkish_case_and_punctuation(self):
        self.assertEqual(quality.normalized('IŞIK, İŞ.  Test!'), 'ışık iş test')
        self.assertEqual(quality.normalized('I\u0307ş'), 'iş')

    def test_changed_fixture_is_rejected_before_any_network_call(self):
        with patch.object(quality, 'EXPECTED', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'only-pinned-synthetic-fixture'):
                quality.validate_fixture()

    def test_unknown_and_missing_speakers_are_not_inferred(self):
        events = [{'source_start_sample': 16000, 'speakerAttribution': {
            'scope': 'one', 'turns': [{'speaker': 'UU', 'startMs': 0, 'endMs': 1000}] }}, {}]
        _, hypothesis = quality.annotations({'turns': []}, events)
        self.assertEqual(len(hypothesis), 0)

    def test_changed_reference_is_rejected_before_any_network_call(self):
        with patch.object(quality, 'EXPECTED_REFERENCE', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'only-pinned-synthetic-reference'):
                quality.validate_fixture()

    def test_offset_and_scope_are_preserved(self):
        events = [{'source_start_sample': 16000, 'speakerAttribution': {
            'scope': scope, 'turns': [{'speaker': 'S1', 'startMs': 500, 'endMs': 1000}] }}
            for scope in ['one', 'two']]
        _, hypothesis = quality.annotations({'turns': []}, events)
        self.assertEqual(hypothesis.labels(), ['one:S1', 'two:S1'])
        self.assertEqual(hypothesis.get_timeline().extent(), quality.Segment(1.5, 2.0))

    def test_der_detects_all_missed_speech(self):
        truth, hypothesis = quality.annotations({'turns': [{'speaker': 'reference',
            'words': [{'start': 1, 'end': 3}]}]}, [])
        score = quality.DiarizationErrorRate(collar=0, skip_overlap=False)(truth, hypothesis)
        self.assertEqual(score, 1.0)


if __name__ == '__main__':
    unittest.main()
