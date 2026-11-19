import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rhythm import TrackRhythm
from spotify_receiver import Receiver, normalize_analysis

TRACK = 'A' * 22

def analysis():
    return {'trackId': TRACK, 'duration': 12, 'tempo': 120,
            'beats': [[float(t), .5, 1] for t in range(1, 11)],
            'segments': [[0, 4, -28, .2, -8, -18, [i / 11 for i in range(12)]],
                         [4, 4, -18, .1, -12, -20, [1 - i / 11 for i in range(12)]],
                         [8, 4, -20, .15, -10, -28, [.6] * 12]]}

class RhythmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('XDG_CACHE_HOME')
        os.environ['XDG_CACHE_HOME'] = str(Path(self.temp.name).resolve())
        self.directory = Path(self.temp.name) / 'orbita-desktop/spotify'
        self.directory.mkdir(parents=True)
        self.payload = {**normalize_analysis(analysis()), 'trackId': TRACK}
        (self.directory / (TRACK + '.analysis.json')).write_text(json.dumps(self.payload))
        self.rhythm = TrackRhythm()
        self.rhythm.update('spotify:track:' + TRACK, 12)

    def tearDown(self):
        if self.old is None:
            os.environ.pop('XDG_CACHE_HOME', None)
        else:
            os.environ['XDG_CACHE_HOME'] = self.old
        self.temp.cleanup()

    def test_beats_pause_seek_and_end(self):
        peak = self.rhythm.sample(1, True)
        self.assertEqual(peak['beat'], 1)
        self.assertGreater(max(peak['bars']), .8)
        self.assertLess(self.rhythm.sample(1.4, True)['beat'], .1)
        self.assertEqual(self.rhythm.sample(.5, True)['beat'], 0)
        self.assertEqual(self.rhythm.sample(1, False)['bars'], [0] * 96)
        self.assertEqual(self.rhythm.sample(12, True)['beat'], 0)
        self.assertEqual(self.rhythm.sample(9, True)['beat'], 1)
        self.assertEqual(self.rhythm.sample(2, True)['beat'], 1)
        self.assertEqual(peak['audio'], 'spotify-analysis')
        self.assertTrue(all(0 <= p <= 1 for p in peak['bars']))

    def test_crossfade_preserves_absolute_times(self):
        self.rhythm.update('spotify:track:' + TRACK, 5)
        self.assertEqual(self.rhythm.sample(9, True)['beat'], 1)
        self.assertEqual(self.rhythm.data['duration'], 12)

    def test_track_switch_and_wrong_version(self):
        self.rhythm.update('https://open.spotify.com/track/' + 'B' * 22, 12)
        self.assertIsNone(self.rhythm.sample(1, True))
        self.rhythm.update('https://open.spotify.com/track/' + TRACK + '?si=test', 12)
        self.assertIsNotNone(self.rhythm.sample(1, True))
        self.rhythm.update('spotify:track:' + TRACK, 25)
        self.assertIsNone(self.rhythm.sample(1, True))
        self.rhythm.update('', 0)
        self.assertIsNone(self.rhythm.sample(1, True))

    def test_analysis_validation(self):
        for change in ('nan', 'order', 'pitch', 'size'):
            value = analysis()
            if change == 'nan': value['beats'][0][0] = math.nan
            if change == 'order': value['beats'].reverse()
            if change == 'pitch': value['segments'][0][-1] = [1]
            if change == 'size': value['beats'] = []
            with self.assertRaises(ValueError, msg=change):
                normalize_analysis(value)

    def test_receiver_auth_and_atomic_analysis(self):
        server = Receiver(('127.0.0.1', 0), 'test-only-key', self.directory)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port) + '/v1/analysis'
        def post(body, token):
            request = urllib.request.Request(url, data=json.dumps(body).encode(),
                    headers={'X-Orbita-Token': token, 'Content-Type': 'application/json'}, method='POST')
            return urllib.request.urlopen(request, timeout=2)
        try:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                post(analysis(), 'wrong')
            self.assertEqual(denied.exception.code, 401)
            with post(analysis(), 'test-only-key') as result:
                self.assertEqual(json.load(result)['beats'], 10)
            file = self.directory / (TRACK + '.analysis.json')
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(file.read_text())['source'], 'spotify')
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                post([], 'test-only-key')
            self.assertEqual(invalid.exception.code, 400)
            self.assertFalse(list(self.directory.glob('*.tmp')))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

if __name__ == '__main__':
    unittest.main()
