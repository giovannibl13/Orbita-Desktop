#!/usr/bin/python3
"""Recebe letras e análise rítmica do cliente local do Spotify."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import signal
import threading
import time
import uuid

ORIGINS = {'https://xpui.app.spotify.com', 'https://open.spotify.com',
           'https://desktop.spotify.com', 'null'}
MAX_BODY = 1024 * 1024


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('number')
    return float(value)


def normalize_analysis(data):
    duration = number(data.get('duration'), 1, 6 * 3600)
    tempo = number(data.get('tempo', 0), 0, 400)
    beats, segments = data.get('beats'), data.get('segments')
    if not isinstance(beats, list) or not 1 <= len(beats) <= 20000:
        raise ValueError('beats')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 15000:
        raise ValueError('segments')
    valid_beats, valid_segments = [], []
    last = -1
    for row in beats:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError('beat')
        start, length, confidence = (number(row[0], 0, duration), number(row[1], .001, 30), number(row[2], 0, 1))
        if start <= last:
            raise ValueError('beat_order')
        last = start
        valid_beats.append([start, length, confidence])
    last = -1
    for row in segments:
        if not isinstance(row, list) or len(row) != 7 or not isinstance(row[6], list) or len(row[6]) != 12:
            raise ValueError('segment')
        start, length = number(row[0], 0, duration), number(row[1], .001, 60)
        if start <= last:
            raise ValueError('segment_order')
        last = start
        valid_segments.append([start, length, number(row[2], -160, 20),
                               number(row[3], 0, length), number(row[4], -160, 20),
                               number(row[5], -160, 20), [number(p, 0, 1) for p in row[6]]])
    return {'duration': duration, 'tempo': tempo, 'beats': valid_beats,
            'segments': valid_segments, 'source': 'spotify'}


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'orbita-desktop' / 'spotify.json'


def cache_path():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'orbita-desktop' / 'spotify'


class Receiver(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, token, directory):
        super().__init__(address, Handler)
        self.token = token
        self.directory = Path(directory)
        self.session_id = uuid.uuid4().hex
        self.last_update = 0
        self.last_track = ''
        self.last_status = 'waiting'
        self.analysis_track = ''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _origin(self):
        return self.headers.get('Origin', '')

    def _reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        origin = self._origin()
        if origin in ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        origin = self._origin()
        if origin and origin not in ORIGINS:
            self._reply(403, {'error': 'origin'})
            return False
        token = self.headers.get('X-Orbita-Token', '')
        if not hmac.compare_digest(token, self.server.token):
            self._reply(401, {'error': 'authorization'})
            return False
        return True

    def do_OPTIONS(self):
        if self._origin() not in ORIGINS:
            self._reply(403, {'error': 'origin'})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self._origin())
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Orbita-Token')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def do_GET(self):
        if not self._authorized():
            return
        if self.path != '/v1/status':
            self._reply(404, {'error': 'path'})
            return
        self._reply(200, {'app': 'orbita', 'session': self.server.session_id,
                          'lastUpdate': self.server.last_update,
                          'trackId': self.server.last_track, 'status': self.server.last_status,
                          'analysisTrackId': self.server.analysis_track})

    def do_POST(self):
        if not self._authorized():
            return
        if self.path not in ('/v1/lyrics', '/v1/analysis'):
            self._reply(404, {'error': 'path'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= MAX_BODY:
                self._reply(413, {'error': 'size'})
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('object')
            track_id = data.get('trackId', '')
            if not isinstance(track_id, str) or not re.fullmatch(r'[A-Za-z0-9]{22}', track_id):
                raise ValueError('track')
            if self.path == '/v1/analysis':
                payload = normalize_analysis(data)
                payload.update(trackId=track_id, saved=time.time())
                self._save(track_id + '.analysis.json', payload)
                self.server.analysis_track = track_id
                self._reply(200, {'ok': True, 'beats': len(payload['beats'])})
                return
            lines = data.get('lines', [])
            if not isinstance(lines, list) or len(lines) > 1000:
                raise ValueError('lines')
            valid = []
            for row in lines:
                if not isinstance(row, dict) or not isinstance(row.get('words'), str):
                    raise ValueError('words')
                stamp = int(row.get('startTimeMs') or 0)
                if not 0 <= stamp <= 24 * 3600 * 1000 or len(row['words']) > 2000:
                    raise ValueError('line')
                valid.append({'startTimeMs': stamp, 'words': row['words']})
            payload = {'trackId': track_id, 'lines': valid, 'source': 'spotify',
                       'syncType': data.get('syncType', 'UNSYNCED'), 'saved': time.time()}
            self._save(track_id + '.json', payload)
            self.server.last_update = time.time()
            self.server.last_track = track_id
            self.server.last_status = 'synced' if valid and payload['syncType'] in ('LINE_SYNCED', 'WORD_SYNCED') else 'plain' if valid else 'unavailable'
            self._reply(200, {'ok': True, 'lines': len(valid)})
        except (ValueError, TypeError, OSError, OverflowError):
            self._reply(400, {'error': 'invalid_payload'})

    def _save(self, name, payload):
        self.server.directory.mkdir(parents=True, exist_ok=True)
        filename = self.server.directory / name
        # O nome temporário é único também em requisições simultâneas.
        temporary = filename.with_name(name + '.' + uuid.uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'))
            temporary.replace(filename)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    config = json.loads(config_path().read_text())
    server = Receiver(('127.0.0.1', int(config.get('port', 45739))), config['token'], cache_path())
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
