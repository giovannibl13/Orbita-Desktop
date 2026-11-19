import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lyrics import Lyrics, choose_record, FetchError
from spotify_receiver import Receiver


def record(title='Faixa Um', artist='Artista Um', duration=200, album='Álbum Um'):
    return {'trackName': title, 'artistName': artist, 'albumName': album,
            'duration': duration, 'syncedLyrics': '[00:00]Linha zero\n[00:10]Linha dez',
            'plainLyrics': 'Linha zero\nLinha dez'}


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.015)
    assert predicate(), 'Tempo de teste excedido'


class LyricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old = os.environ.get('XDG_CACHE_HOME')
        os.environ['XDG_CACHE_HOME'] = str(Path(self.directory.name).resolve())
        self.stop = threading.Event()
        self.client = Lyrics(self.stop)

    def tearDown(self):
        self.stop.set()
        self.client.wake.set()
        self.client.worker.join(timeout=2)
        self.directory.cleanup()
        if self.old is None:
            os.environ.pop('XDG_CACHE_HOME', None)
        else:
            os.environ['XDG_CACHE_HOME'] = self.old

    def test_versions_and_artists(self):
        rows = [record(artist='Outra pessoa'), record(album='Ao Vivo'), record(duration=201)]
        found, mode = choose_record(rows, 'Faixa Um', 'Artista Um', 'Álbum Um', 200)
        self.assertEqual((found['duration'], mode), (201, 'synced'))
        self.assertEqual(choose_record(rows[:2], 'Faixa Um', 'Artista Um', 'Álbum Um', 200), (None, 'unavailable'))

    def test_repeated_lines_have_distinct_cues(self):
        self.client.rows = [(1, 'Mesma linha'), (5, 'Mesma linha'), (9, 'Outra linha')]
        self.assertEqual(self.client.at(2)[0], self.client.at(6)[0])
        self.assertEqual(self.client.cue(2), 1)
        self.assertEqual(self.client.cue(6), 5)
        self.assertEqual(self.client.cue(0), -1)

    def test_404_search_for_any_track(self):
        calls = []
        def request(endpoint, args):
            calls.append(endpoint)
            if endpoint == 'get':
                raise FetchError(404)
            return [record(title=args['track_name'], artist=args.get('artist_name', 'Artista Um'), duration=205)]
        self.client._request = request
        self.client.update('Outra Faixa', 'Artista Um', 'Álbum Um', 200)
        wait_for(lambda: self.client.state != 'loading')
        self.assertEqual(self.client.state, 'estimated')
        self.assertIn('Sincronização aproximada', self.client.at(30)[1])
        self.assertEqual(calls, ['get', 'search'])
        self.client.update('Terceira Faixa', 'Artista Um', 'Álbum Um', 200)
        wait_for(lambda: self.client.state != 'loading')
        self.assertEqual(self.client.key[0], 'Terceira Faixa')
        self.assertEqual(calls, ['get', 'search', 'get', 'search'])

    def test_spotify_overrides_external(self):
        def request(endpoint, args):
            time.sleep(.07)
            return record()
        self.client._request = request
        track_id = 'A' * 22
        self.client.update('Faixa Um', 'Artista Um', 'Álbum Um', 200, 'spotify:track:' + track_id)
        directory = Path(os.environ['XDG_CACHE_HOME']) / 'orbita-desktop/spotify'
        directory.mkdir(parents=True)
        (directory / (track_id + '.json')).write_text(json.dumps({
            'trackId': track_id, 'syncType': 'LINE_SYNCED',
            'lines': [{'startTimeMs': 1000, 'words': 'Linha da fonte principal'}]}))
        self.client.update('Faixa Um', 'Artista Um', 'Álbum Um', 200, 'spotify:track:' + track_id)
        self.assertEqual(self.client.source, 'spotify')
        time.sleep(.15)
        self.assertEqual(self.client.at(2)[0], 'Linha da fonte principal')
        self.assertEqual(self.client.state, 'synced')

    def test_transient_error_retries(self):
        attempts = []
        def request(endpoint, args):
            attempts.append(endpoint)
            if len(attempts) == 1:
                raise FetchError('network', .05)
            return record()
        self.client._request = request
        self.client.update('Faixa Um', 'Artista Um', 'Álbum Um', 200)
        wait_for(lambda: self.client.state == 'error')
        time.sleep(.06)
        self.client.update('Faixa Um', 'Artista Um', 'Álbum Um', 200)
        wait_for(lambda: self.client.state == 'synced')
        self.assertEqual(len(attempts), 2)


class ReceiverTests(unittest.TestCase):
    def test_authorization_and_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Receiver(('127.0.0.1', 0), 'test-token', directory)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_address[1]}'
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + '/v1/status')
                self.assertEqual(error.exception.code, 401)
                req = urllib.request.Request(base + '/v1/status', headers={
                    'X-Orbita-Token': 'test-token', 'Origin': 'https://invalid.example'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req)
                self.assertEqual(error.exception.code, 403)
                data = {'trackId': 'A' * 22, 'syncType': 'LINE_SYNCED',
                        'lines': [{'startTimeMs': 1500, 'words': 'Linha de teste'}]}
                req = urllib.request.Request(base + '/v1/lyrics', data=json.dumps(data).encode(), headers={
                    'X-Orbita-Token': 'test-token', 'Origin': 'https://xpui.app.spotify.com',
                    'Content-Type': 'application/json'})
                with urllib.request.urlopen(req) as result:
                    self.assertEqual(json.load(result), {'ok': True, 'lines': 1})
                saved = json.loads((Path(directory) / ('A' * 22 + '.json')).read_text())
                self.assertEqual(saved['lines'][0]['startTimeMs'], 1500)
                self.assertEqual(server.last_status, 'synced')
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
