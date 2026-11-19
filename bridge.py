#!/usr/bin/python3
"""Áudio de saída + MPRIS. O protocolo de saída é JSON por linha."""
import array
import ctypes
import ctypes.util
import json
import math
import os
import select
import signal
import subprocess
import sys
import threading
import time

from gi.repository import Gio, GLib
from lyrics import Lyrics, parse_lrc
from rhythm import TrackRhythm
from artwork import Artwork

N = 2048
RATE = 22050
BANDS = 96
STOP = threading.Event()


class Spectrum:
    """FFT nativa. A biblioteca já acompanha o Zorin deste computador."""
    def __init__(self):
        library = ctypes.util.find_library('fftw3')
        if not library:
            raise RuntimeError('Biblioteca libfftw3 não encontrada')
        self.lib = ctypes.CDLL(library)
        self.samples = (ctypes.c_double * N)()
        self.result = (ctypes.c_double * (N + 2))()
        self.lib.fftw_plan_dft_r2c_1d.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_uint]
        self.lib.fftw_plan_dft_r2c_1d.restype = ctypes.c_void_p
        self.lib.fftw_execute.argtypes = [ctypes.c_void_p]
        self.lib.fftw_destroy_plan.argtypes = [ctypes.c_void_p]
        self.plan = self.lib.fftw_plan_dft_r2c_1d(N, self.samples, self.result, 64)
        if not self.plan:
            raise RuntimeError('Não foi possível criar a FFT')
        self.window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]
        self.ranges = []
        for i in range(BANDS):
            lo = max(1, int(40 * (10000 / 40) ** (i / BANDS) * N / RATE))
            hi = min(N // 2, max(lo + 1, int(40 * (10000 / 40) ** ((i + 1) / BANDS) * N / RATE)))
            self.ranges.append((lo, hi))

    def analyze(self, samples):
        for i in range(N):
            self.samples[i] = samples[i] * self.window[i]
        self.lib.fftw_execute(self.plan)
        bars = []
        for lo, hi in self.ranges:
            power = max(self.result[2*k] ** 2 + self.result[2*k+1] ** 2 for k in range(lo, hi))
            db = 20 * math.log10(max(1e-8, math.sqrt(power) / (N / 2)))
            bars.append(round(max(0, min(1, (db + 70) / 65)), 3))
        return bars

    def close(self):
        if self.plan:
            self.lib.fftw_destroy_plan(self.plan)
            self.plan = None


def unpack(value):
    if isinstance(value, GLib.Variant):
        return unpack(value.unpack())
    if isinstance(value, dict):
        return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [unpack(v) for v in value]
    return value


class Player:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.names = []
        self.last_list = 0
        self.lyrics = Lyrics(STOP)
        self.rhythm = TrackRhythm()
        self.artwork = Artwork(STOP)
        self.state = self.empty()
        self.last_position = 0

    @staticmethod
    def empty():
        return {'title': 'Sua música, em órbita', 'artist': 'Abra seu player e dê play',
                'playback': 'Stopped', 'position': 0, 'duration': 0, 'lyric': '',
                'nextLyric': '', 'lyricsState': 'idle', 'player': '', 'artPath': ''}

    def call(self, name, path, interface, method, args=None):
        return unpack(self.bus.call_sync(name, path, interface, method, args, None,
                                        Gio.DBusCallFlags.NONE, 250, None))

    def poll(self):
        now = time.monotonic()
        if now - self.last_list >= 3:
            self.last_list = now
            try:
                names = self.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'ListNames')[0]
                self.names = sorted((n for n in names if n.startswith('org.mpris.MediaPlayer2.')),
                                    key=lambda n: ('spotify' not in n.lower(), n))
            except GLib.Error:
                self.names = []
        chosen = None
        for name in self.names[:6]:
            try:
                props = self.call(name, '/org/mpris/MediaPlayer2',
                                  'org.freedesktop.DBus.Properties', 'GetAll',
                                  GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',)))[0]
                if chosen is None or props.get('PlaybackStatus') == 'Playing':
                    chosen = name, props
                if props.get('PlaybackStatus') == 'Playing':
                    break
            except GLib.Error:
                continue
        if chosen is None:
            self.state = self.empty()
            self.rhythm.update('', 0)
            self.artwork.update('')
        else:
            name, props = chosen
            meta = props.get('Metadata', {})
            self.artwork.update(meta.get('mpris:artUrl', ''))
            title = meta.get('xesam:title') or 'Faixa sem título'
            artist = ', '.join(meta.get('xesam:artist', []))
            duration = meta.get('mpris:length', 0) / 1e6
            self.rhythm.update(meta.get('xesam:url', ''), duration)
            if self.rhythm.data:
                duration = self.rhythm.data['duration']
            self.state = {'title': title, 'artist': artist,
                          'duration': duration, 'position': props.get('Position', 0) / 1e6,
                          'playback': props.get('PlaybackStatus', 'Stopped'),
                          'player': name, 'rate': props.get('Rate', 1.0),
                          'canControl': bool(props.get('CanControl', True)),
                          'canPrevious': bool(props.get('CanGoPrevious', False)),
                          'canNext': bool(props.get('CanGoNext', False)),
                          'canPlayPause': bool(props.get('CanPause' if props.get('PlaybackStatus') == 'Playing' else 'CanPlay', True))}
            if artist and title != 'Faixa sem título':
                self.lyrics.update(title, artist, meta.get('xesam:album', ''), duration, meta.get('xesam:url', ''))
        self.last_position = now

    def snapshot(self):
        state = dict(self.state)
        state['artPath'], state['artState'] = self.artwork.snapshot()
        if state['playback'] == 'Playing':
            state['position'] += (time.monotonic() - self.last_position) * state.get('rate', 1)
        if state['duration']:
            state['position'] = min(state['position'], state['duration'])
        if state.get('player'):
            state['lyric'], state['nextLyric'] = self.lyrics.at(state['position'])
            state['lyricCue'] = self.lyrics.cue(state['position'])
            state['lyricsState'] = self.lyrics.state
            state['lyricsSource'] = self.lyrics.source
            state['lyricsError'] = self.lyrics.error
            state['rhythm'] = self.rhythm.sample(state['position'], state['playback'] == 'Playing')
        return state


def run():
    spectrum = Spectrum()
    player = Player()
    process = None
    try:
        process = subprocess.Popen(
            ['pw-cat', '--record', '--rate=' + str(RATE), '--channels=1', '--format=f32',
             '--latency=80ms',
             '--properties={"stream.capture.sink":true,"application.name":"Órbita Desktop","media.role":"DSP"}', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(process.stdout.fileno(), False)
        pending = bytearray()
        bars = [0.0] * BANDS
        last_poll, last_emit, last_audio, last_signal = 0, 0, 0, -10
        while not STOP.is_set():
            now = time.monotonic()
            if now - last_poll >= 0.8:
                player.poll()
                last_poll = now
            ready, _, _ = select.select([process.stdout], [], [], 0.02)
            if ready:
                chunk = os.read(process.stdout.fileno(), N * 4 * 8)
                if not chunk:
                    raise RuntimeError('A captura de áudio foi encerrada')
                pending.extend(chunk)
            if len(pending) >= N * 4:
                # Descarta blocos antigos para manter a resposta junto do áudio.
                take = (len(pending) // (N * 4)) * (N * 4)
                raw = pending[take - N * 4:take]
                del pending[:take]
                samples = array.array('f')
                samples.frombytes(raw)
                bars = spectrum.analyze(samples)
                last_audio = now
                if max(bars) > .04:
                    last_signal = now
            elif now - last_audio > 0.3:
                bars = [0.0] * BANDS
            if now - last_emit >= 1 / 24:
                state = player.snapshot()
                rhythm = state.pop('rhythm', None)
                state.update({'bars': bars, 'audio': 'output', 'beat': 0, 'version': 2})
                if rhythm and now - last_signal > .35:
                    state.update(rhythm)
                print(json.dumps(state, ensure_ascii=False, separators=(',', ':')), flush=True)
                last_emit = now
    except BrokenPipeError:
        pass
    finally:
        STOP.set()
        if process:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        spectrum.close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    try:
        run()
    except Exception as error:
        print(json.dumps({'error': str(error)}), flush=True)
        sys.exit(1)
