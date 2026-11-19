import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artwork import Artwork
from gi.repository import GdkPixbuf


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    assert predicate(), 'Tempo de teste excedido'


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.previous = os.environ.get('XDG_CACHE_HOME')
        os.environ['XDG_CACHE_HOME'] = str(self.root / 'cache')
        self.image = self.root / 'Capa com espaço.png'
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 500, 300)
        pixbuf.fill(0xE25B24FF)
        pixbuf.savev(str(self.image), 'png', [], [])
        self.stop = threading.Event()
        self.art = Artwork(self.stop)

    def tearDown(self):
        self.stop.set()
        self.art.wake.set()
        self.art.worker.join(2)
        if self.previous is None:
            os.environ.pop('XDG_CACHE_HOME', None)
        else:
            os.environ['XDG_CACHE_HOME'] = self.previous
        self.temp.cleanup()

    def test_local_cache_and_update(self):
        self.art.update(self.image.as_uri())
        wait_for(lambda: self.art.snapshot()[1] == 'ready')
        path, _ = self.art.snapshot()
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), (256, 256))
        self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
        self.art.update('')
        self.assertEqual(self.art.snapshot(), ('', 'idle'))
        self.art.update(self.image.as_uri())
        wait_for(lambda: self.art.snapshot()[1] == 'ready')
        self.assertEqual(self.art.snapshot()[0], path)
        pixbuf.fill(0x2467E2FF)
        pixbuf.savev(str(self.image), 'png', [], [])
        self.art.update(self.image.as_uri())
        wait_for(lambda: self.art.snapshot()[1] == 'ready')
        self.assertNotEqual(self.art.snapshot()[0], path)

    def test_missing_and_invalid_image(self):
        self.art.update('file:///arquivo-de-capa-que-nao-existe.png')
        self.assertEqual(self.art.snapshot(), ('', 'idle'))
        self.image.write_text('imagem inválida')
        self.art.update(self.image.as_uri())
        wait_for(lambda: self.art.snapshot()[1] == 'unavailable')
        self.assertEqual(self.art.snapshot()[0], '')
        self.assertTrue(self.art.worker.is_alive())

    def test_old_request_cannot_replace_new_cover(self):
        started, release = threading.Event(), threading.Event()
        def load(uri, key):
            if uri.endswith('/old'):
                started.set()
                release.wait(2)
                return '/old.png'
            return '/new.png'
        self.art._load = load
        self.art.update('https://test.invalid/old')
        self.assertTrue(started.wait(1))
        self.art.update('https://test.invalid/new')
        release.set()
        wait_for(lambda: self.art.snapshot()[1] == 'ready')
        self.assertEqual(self.art.snapshot(), ('/new.png', 'ready'))

    def test_http_download_and_cache(self):
        raw = self.image.read_bytes()
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                calls.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            uri = 'http://127.0.0.1:' + str(server.server_port) + '/cover'
            self.art.update(uri)
            wait_for(lambda: self.art.snapshot()[1] == 'ready')
            self.art.update('')
            self.art.update(uri)
            wait_for(lambda: self.art.snapshot()[1] == 'ready')
            self.assertEqual(calls, ['/cover'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == '__main__':
    unittest.main()
