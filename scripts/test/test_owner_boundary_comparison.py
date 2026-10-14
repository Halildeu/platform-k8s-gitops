"""Offline validation of fixture identity, actual client wire and trace checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/faz24'))
import compare_owner_boundary as probe


class OwnerComparisonTests(unittest.TestCase):
    def test_audio_and_both_source_profiles_are_exact(self):
        manifest=json.loads((probe.FIXTURES/'manifest.json').read_text())
        for case in manifest['cases']:
            name=case['name']
            audio=probe.FIXTURES/(name+'.wav')
            self.assertEqual(probe.digest(audio.read_bytes()),case['sha256'])
            with wave.open(str(audio),'rb') as wav:
                self.assertEqual((wav.getnchannels(),wav.getframerate(),wav.getsampwidth()),(1,16000,2))
                pcm=wav.readframes(wav.getnframes())
            mobile=probe.wire_frames(name,'mobile')
            desktop=probe.wire_frames(name,'desktop')
            self.assertEqual(mobile,desktop)
            self.assertEqual(b''.join(frame[19:] for frame in mobile),pcm)

    def test_cursor_match_requires_exact_source(self):
        events=[{'text':'Mehmet.'},{'text':' Bütçe tablosunu kontrol edecek. '}]
        text='Mehmet. Bütçe tablosunu kontrol edecek.'
        snapshot={'live_cursor':{'source_length':len(text),'source_sha256':probe.digest(text)}}
        self.assertEqual(probe.verified_input(events,snapshot),text)
        events[0]['text']='Zeynep.'
        self.assertIsNone(probe.verified_input(events,snapshot))
        self.assertIsNone(probe.verified_input(events,{}))

    def test_sse_chunking_retains_rejection_without_tokens(self):
        observer=probe.SnapshotObserver()
        observer.recording=True
        body={'grounding_policy':'verified_only','version':8,'is_partial':True,
              'summary':'','decisions':[],'action_items':[{'text':'Bütçe tablosunu kontrol edecek.','owner':None}],
              'rejected_claims':[{'kind':'action_owner','claim':'Mehmet','reason':'not in source'}],
              'unknownPrivateField':'must-not-be-retained'}
        data=('event: analysis\ndata: '+json.dumps(body,ensure_ascii=False)+'\n\n').encode()
        for start in range(0,len(data),7): observer.push(data[start:start+7])
        self.assertEqual(len(observer.snapshots),1)
        saved=observer.snapshots[0]
        self.assertTrue(saved['beforeEof'])
        self.assertEqual(saved['analysis']['rejected_claims'][0]['kind'],'action_owner')
        self.assertNotIn('unknownPrivateField',saved['analysis'])


if __name__=='__main__': unittest.main()
