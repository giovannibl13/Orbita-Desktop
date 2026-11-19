"""Animação rítmica pelos tempos e pela intensidade da gravação do Spotify."""
from bisect import bisect_right
import json
import math
import os
from pathlib import Path
import re
import time


class TrackRhythm:
    def __init__(self):
        self.track_id = ''
        self.data = None
        self.beat_times = []
        self.segment_times = []
        self.next_check = 0
        self.stamp = None

    def update(self, uri, duration):
        match = re.search(r'(?:spotify:track:|open\.spotify\.com/track/)([A-Za-z0-9]{22})(?:[?/#]|$)', uri or '')
        track_id = match[1] if match else ''
        if track_id != self.track_id:
            self.track_id, self.data = track_id, None
            self.beat_times, self.segment_times = [], []
            self.next_check, self.stamp = 0, None
        if self.data and duration and not -2 <= self.data['duration'] - duration <= 15:
            self.data, self.stamp, self.next_check = None, None, 0
        now = time.monotonic()
        if not track_id or now < self.next_check:
            return
        self.next_check = now + 1
        directory = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'orbita-desktop' / 'spotify'
        filename = directory / (track_id + '.analysis.json')
        try:
            stat = filename.stat()
            if stat.st_mtime_ns == self.stamp or stat.st_size > 1024 * 1024:
                return
            data = json.loads(filename.read_text())
            # O identificador deve corresponder à gravação em reprodução.
            if data.get('trackId') != track_id or data.get('source') != 'spotify':
                return
            # O MPRIS do Spotify subtrai o crossfade da duração, mas mantém
            # a posição absoluta da faixa. Preserva os tempos originais.
            if duration and not -2 <= data['duration'] - duration <= 15:
                self.data = None
                return
            if not data.get('beats') or not data.get('segments'):
                return
            self.beat_times = [beat[0] for beat in data['beats']]
            self.segment_times = [segment[0] for segment in data['segments']]
            self.data, self.stamp = data, stat.st_mtime_ns
        except (OSError, ValueError, KeyError, TypeError):
            self.data = None

    def sample(self, position, playing):
        if not self.data:
            return None
        if not playing or not 0 <= position < self.data['duration']:
            return {'bars': [0.0] * 96, 'beat': 0.0, 'audio': 'spotify-analysis'}
        beat_index = bisect_right(self.beat_times, position) - 1
        pulse = 0
        if beat_index >= 0:
            start, length, confidence = self.data['beats'][beat_index]
            if position - start < length:
                pulse = math.exp(-(position - start) / min(.16, length * .32)) * (.65 + .35 * confidence)
        index = bisect_right(self.segment_times, position) - 1
        bars = [0.0] * 96
        if index >= 0:
            start, length, low, peak_time, peak, end, pitches = self.data['segments'][index]
            elapsed = position - start
            if elapsed <= length + .05:
                if elapsed < peak_time:
                    loudness = low + (peak - low) * elapsed / max(.001, peak_time)
                else:
                    # O serviço usa zero como sentinela em segmentos não finais.
                    if end == 0 and index + 1 < len(self.data['segments']):
                        end = self.data['segments'][index + 1][2]
                    progress = min(1, (elapsed - peak_time) / max(.001, length - peak_time))
                    loudness = peak + (end - peak) * progress
                energy = max(0, min(1, (loudness + 52) / 46)) ** 1.5
                # Desenho dos raios pela intensidade e pelas classes de altura da
                # análise. Esta fonte não representa uma FFT capturada no PC.
                for band in range(96):
                    p = band / 95 * 11
                    left = int(p)
                    pitch = pitches[left] * (1 - p + left) + pitches[min(11, left + 1)] * (p - left)
                    bars[band] = round(min(1, energy * (.13 + .34 * pitch) +
                                            pulse * energy * (.35 + .32 * pitch)), 3)
        return {'bars': bars, 'beat': round(pulse, 3), 'audio': 'spotify-analysis'}
