"""Letras do Spotify, com busca alternativa no LRCLIB para qualquer faixa."""
import bisect
import collections
import email.utils
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


def cache_directory():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'orbita-desktop'


def parse_lrc(text):
    rows = []
    for line in text.splitlines():
        stamps = re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', line)
        words = re.sub(r'\[[^\]]*\]', '', line).strip()
        for minute, second in stamps:
            rows.append((int(minute) * 60 + float(second), words))
    return sorted(rows)


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(text)).casefold()
                   if not unicodedata.combining(c))
    text = re.sub(r'\b(?:and|e|feat|featuring|ft)\b', ' ', text)
    return re.sub(r'[^a-z0-9]', '', text)


def title_key(text):
    text = re.sub(r'\s*[-([]\s*(?:\d{4}\s*)?(?:re)?master(?:ed)?[^\])]*[\])]?$','',text,flags=re.I)
    return normalize(text)


def version_kind(title, album):
    text = ''.join(c for c in unicodedata.normalize('NFKD', f'{title} {album}').casefold()
                   if not unicodedata.combining(c))
    if re.search(r'\bao vivo\b|\blive\b|\ben vivo\b', text):
        return 'live'
    if re.search(r'\bacoustic\b|\bacustic', text):
        return 'acoustic'
    if re.search(r'\bremix\b', text):
        return 'remix'
    return 'studio'


def estimated_plain_rows(text, duration):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    duration = duration if duration > 15 else max(60, len(lines) * 4)
    intro = min(10, duration * 0.05)
    span = max(1, duration - intro - min(6, duration * 0.03))
    weights = [max(12, len(line)) for line in lines]
    total = sum(weights)
    elapsed, result = 0, []
    for line, weight in zip(lines, weights):
        result.append((intro + span * elapsed / total, line))
        elapsed += weight
    return result


def choose_record(records, title, artist, album, duration):
    """Preserva artista/título e distingue gravações ao vivo, acústicas e remixes."""
    candidates = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate_title = record.get('trackName') or record.get('name') or ''
        if title_key(candidate_title) != title_key(title):
            continue
        candidate_artist = record.get('artistName') or ''
        same_artist = normalize(candidate_artist) == normalize(artist)
        if not same_artist:
            # Alguns registros incluem participações ou texto extra no artista.
            left = normalize(candidate_artist.split(',')[0])
            right = normalize(artist.split(',')[0])
            if left != right:
                continue
        if version_kind(candidate_title, record.get('albumName', '')) != version_kind(title, album):
            continue
        candidate_duration = float(record.get('duration') or 0)
        delta = abs(candidate_duration - duration) if candidate_duration and duration else 0
        synced = bool(parse_lrc(record.get('syncedLyrics') or ''))
        if synced and duration and candidate_duration and delta <= 2.5:
            mode = 'synced'
        elif synced and duration and candidate_duration and delta <= min(12, duration * 0.06):
            mode = 'estimated'
        elif record.get('plainLyrics') and (delta <= 30 or not duration or not candidate_duration):
            mode = 'plain-estimated'
        else:
            continue
        rank = ({'synced': 0, 'estimated': 1, 'plain-estimated': 2}[mode],
                not same_artist, normalize(record.get('albumName', '')) != normalize(album), delta)
        candidates.append((rank, record, mode))
    if not candidates:
        return None, 'unavailable'
    _, record, mode = min(candidates, key=lambda item: item[0])
    return record, mode


class FetchError(Exception):
    def __init__(self, code, retry=30):
        self.code, self.retry = code, retry
        super().__init__(str(code))


class Lyrics:
    def __init__(self, stop=None):
        self.stop = stop or threading.Event()
        self.key = None
        self.rows = []
        self.state = 'idle'
        self.source = ''
        self.error = ''
        self.track_id = ''
        self.spotify_mtime = 0
        self.retry_at = 0
        self.next_request = 0
        self.jobs = collections.deque(maxlen=1)
        self.wake = threading.Event()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def update(self, title, artist, album, duration, uri=''):
        key = (title, artist, album, round(duration))
        match = re.search(r'(?:spotify:track:|open\.spotify\.com/track/)([A-Za-z0-9]{22})', uri)
        track_id = match.group(1) if match else ''
        if key != self.key or track_id != self.track_id:
            self.key, self.track_id = key, track_id
            self.rows, self.state, self.source, self.error = [], 'loading', '', ''
            self.spotify_mtime, self.retry_at = 0, 0
            self.jobs.append(key)
            self.wake.set()
        self._read_spotify(duration)
        if self.source != 'spotify' and self.state == 'error' and time.monotonic() >= self.retry_at:
            self.state = 'loading'
            self.jobs.append(key)
            self.wake.set()

    def _read_spotify(self, duration):
        if not self.track_id:
            return
        filename = cache_directory() / 'spotify' / (self.track_id + '.json')
        try:
            stamp = filename.stat().st_mtime_ns
            if stamp == self.spotify_mtime:
                return
            data = json.loads(filename.read_text())
            if data.get('trackId') != self.track_id or not data.get('lines'):
                return
            if data.get('syncType') in ('LINE_SYNCED', 'WORD_SYNCED'):
                rows = sorted((float(row['startTimeMs']) / 1000, str(row['words']))
                              for row in data['lines'])
                mode = 'synced'
            else:
                rows = estimated_plain_rows('\n'.join(str(row['words']) for row in data['lines']), duration)
                mode = 'estimated'
            self.rows, self.state, self.source, self.error = rows, mode, 'spotify', ''
            self.spotify_mtime = stamp
        except (OSError, ValueError, TypeError, KeyError):
            return

    def _request(self, endpoint, args):
        if self.stop.wait(max(0, self.next_request - time.monotonic())):
            raise FetchError('stopped', 60)
        request = urllib.request.Request(
            'https://lrclib.net/api/' + endpoint + '?' + urllib.parse.urlencode(args),
            headers={'User-Agent': 'OrbitaDesktop/1.0.0 (https://github.com/giovannibl13)'})
        try:
            with urllib.request.urlopen(request, timeout=7) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            delay = 60 if error.code == 429 else 30
            retry = error.headers.get('Retry-After')
            if retry:
                try:
                    delay = max(1, float(retry))
                except ValueError:
                    try:
                        delay = max(1, email.utils.parsedate_to_datetime(retry).timestamp() - time.time())
                    except (TypeError, ValueError):
                        pass
            raise FetchError(error.code, delay) from error
        except (OSError, ValueError) as error:
            raise FetchError('network', 30) from error
        finally:
            self.next_request = time.monotonic() + 0.35

    def _lookup(self, key):
        title, artist, album, duration = key
        args = {'track_name': title, 'artist_name': artist}
        if album:
            args['album_name'] = album
        if 0 < duration <= 3600:
            args['duration'] = duration
        records = []
        try:
            direct = self._request('get', args)
            records.append(direct)
            if direct.get('instrumental'):
                return direct, 'instrumental'
            if direct.get('syncedLyrics'):
                return direct, 'synced'
        except FetchError as error:
            if error.code != 404:
                raise
        results = self._request('search', {'track_name': title, 'artist_name': artist})
        records.extend(results if isinstance(results, list) else [])
        record, mode = choose_record(records, title, artist, album, duration)
        if record and mode in ('synced', 'estimated'):
            return record, mode
        # Busca pelo título permite encontrar grafias diferentes de duplas e participações.
        results = self._request('search', {'track_name': title})
        records.extend(results if isinstance(results, list) else [])
        return choose_record(records, title, artist, album, duration)

    def _worker(self):
        while not self.stop.is_set():
            self.wake.wait(0.5)
            self.wake.clear()
            if not self.jobs:
                continue
            key = self.jobs.pop()
            if self.source == 'spotify' and self.key == key:
                continue
            filename = cache_directory() / (hashlib.sha256(json.dumps(key).encode()).hexdigest() + '.json')
            data, mode = None, None
            try:
                try:
                    cached = json.loads(filename.read_text())
                    if time.time() - cached.get('saved', 0) < 30 * 86400:
                        data = cached.get('data')
                        if cached.get('schema') == 2:
                            mode = cached.get('mode')
                        elif data:
                            mode = 'synced' if data.get('syncedLyrics') else None
                except (OSError, ValueError, TypeError):
                    pass
                if not data or not mode:
                    data, mode = self._lookup(key)
                    if data:
                        try:
                            filename.parent.mkdir(parents=True, exist_ok=True)
                            filename.write_text(json.dumps({'schema': 2, 'saved': time.time(),
                                                            'data': data, 'mode': mode}))
                        except OSError:
                            pass
                if data and mode in ('synced', 'estimated'):
                    rows = parse_lrc(data.get('syncedLyrics') or '')
                    if mode == 'estimated' and data.get('duration'):
                        scale = key[3] / float(data['duration'])
                        rows = [(stamp * scale, words) for stamp, words in rows]
                elif data and mode == 'plain-estimated':
                    rows = estimated_plain_rows(data.get('plainLyrics') or '', key[3])
                    mode = 'estimated'
                else:
                    rows = []
                    mode = 'instrumental' if mode == 'instrumental' else 'unavailable'
                if self.key == key and self.source != 'spotify':
                    self.rows, self.state, self.source, self.error = rows, mode, 'lrclib', ''
            except FetchError as error:
                if self.key == key and self.source != 'spotify':
                    self.state, self.error = 'error', str(error.code)
                    self.retry_at = time.monotonic() + error.retry
            except Exception:
                if self.key == key and self.source != 'spotify':
                    self.state, self.error = 'error', 'parse'
                    self.retry_at = time.monotonic() + 30

    def cue(self, position):
        rows = self.rows
        index = bisect.bisect_right([row[0] for row in rows], position) - 1
        return rows[index][0] if 0 <= index < len(rows) else -1

    def at(self, position):
        rows = self.rows
        index = bisect.bisect_right([row[0] for row in rows], position) - 1
        current = rows[index][1] if 0 <= index < len(rows) else ''
        following = rows[index + 1][1] if 0 <= index + 1 < len(rows) else ''
        if self.state == 'estimated':
            following = 'Sincronização aproximada' + (' · ' + following if following else '')
        elif self.state == 'error':
            following = 'Falha ao buscar a letra. Tentando novamente…'
        elif self.state == 'unavailable':
            following = 'Letra não encontrada para esta faixa'
        elif self.state == 'instrumental':
            following = 'Faixa instrumental'
        return current, following
