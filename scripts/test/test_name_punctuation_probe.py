import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).parents[1] / 'faz24/probe_name_punctuation.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PunctuationProbeTest(unittest.TestCase):
    def test_split_owner_is_not_counted_as_an_intact_task(self):
        result = probe.metrics('Zeynep . Sunum dosyasını hazırlayacak . Mehmet . Bütçe tablosunu kontrol edecek .')
        self.assertEqual(result['namesFound'], 2)
        self.assertEqual(result['nameFullStops'], 2)
        self.assertEqual(result['intactOwnerTasks'], 0)
        self.assertEqual(result['sentenceTerminators'], 2)
        self.assertNotIn('Zeynep', str(result))

    def test_complete_owner_tasks_and_real_terminators(self):
        result = probe.metrics('Sunumu çevrim içi yapmaya karar verdik. Zeynep sunum dosyasını hazırlayacak. '
                               'Mehmet bütçe tablosunu kontrol edecek. Ayşe test raporunu hazırlayacak.')
        self.assertEqual(result['namesFound'], 3)
        self.assertEqual(result['nameFullStops'], 0)
        self.assertEqual(result['intactOwnerTasks'], 3)
        self.assertEqual(result['sentenceTerminators'], 4)

    def test_pinned_audio_format_and_identity(self):
        self.assertGreater(len(probe.fixture_pcm()), 32000)
        with self.assertRaises(ValueError):
            probe.fixture_pcm(Path(__file__))


if __name__ == '__main__':
    unittest.main()
