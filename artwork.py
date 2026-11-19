"""Carrega capas do MPRIS em segundo plano e mantém um cache de miniaturas."""
import hashlib
from http.client import HTTPException
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gio, GLib

MAX_BYTES = 8 * 1024 * 1024
SIZE = 256


class Artwork:
    def __init__(self, stop):
        self.stop = stop
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.key = ''
        self.uri = ''
        self.path = ''
        self.state = 'idle'
        self.retry_at = 0
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def update(self, uri):
        uri = uri if isinstance(uri, str) and len(uri) <= 4096 else ''
        key = uri
        try:
            parsed = urlsplit(uri)
            if parsed.scheme not in ('https', 'http', 'file'):
                uri, key = '', ''
            elif parsed.scheme == 'file':
                if parsed.netloc not in ('', 'localhost'):
                    raise ValueError('file_host')
                stat = Path(unquote(parsed.path)).stat()
                key += ':' + str(stat.st_mtime_ns) + ':' + str(stat.st_size)
        except (OSError, ValueError):
            uri, key = '', ''
        with self.lock:
            if key == self.key and not (self.state == 'unavailable' and time.monotonic() >= self.retry_at):
                return
            self.key, self.uri, self.path = key, uri, ''
            self.state = 'loading' if uri else 'idle'
            self.retry_at = 0
        self.wake.set()

    def snapshot(self):
        with self.lock:
            return self.path, self.state

    def _run(self):
        while not self.stop.is_set():
            if not self.wake.wait(.3):
                continue
            self.wake.clear()
            with self.lock:
                key, uri = self.key, self.uri
            if not uri:
                continue
            try:
                path = self._load(uri, key)
            except (OSError, ValueError, GLib.Error, HTTPException):
                path = ''
            with self.lock:
                # Uma consulta antiga não pode recolocar a capa da faixa anterior.
                if key == self.key:
                    self.path = path
                    self.state = 'ready' if path else 'unavailable'
                    self.retry_at = time.monotonic() + 30

    def _load(self, uri, key):
        directory = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'orbita-desktop' / 'artwork'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = directory / (hashlib.sha256(key.encode()).hexdigest() + '.png')
        if filename.is_file():
            try:
                image = GdkPixbuf.Pixbuf.new_from_file(str(filename))
                if image.get_width() == SIZE and image.get_height() == SIZE:
                    return str(filename)
            except GLib.Error:
                pass
        parsed = urlsplit(uri)
        if parsed.scheme == 'file':
            with Path(unquote(parsed.path)).open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        else:
            request = Request(uri, headers={'User-Agent': 'OrbitaDesktop/7', 'Accept': 'image/*'})
            with urlopen(request, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('image_size')
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(raw))
        try:
            image = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, SIZE * 2, SIZE * 2, True, None)
            image = image.apply_embedded_orientation()
        finally:
            stream.close(None)
        width, height = image.get_width(), image.get_height()
        side = min(width, height)
        image = image.new_subpixbuf((width - side) // 2, (height - side) // 2, side, side)
        image = image.scale_simple(SIZE, SIZE, GdkPixbuf.InterpType.BILINEAR)
        descriptor, temporary = tempfile.mkstemp(prefix='.capa-', suffix='.png', dir=directory)
        os.close(descriptor)
        try:
            image.savev(temporary, 'png', [], [])
            os.replace(temporary, filename)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return str(filename)
