#!/usr/bin/python3
"""Verificações de código e testes das integrações do Órbita."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for path in ROOT.rglob('*.py'):
        if not any(part in ('dist', 'build', '__pycache__') for part in path.relative_to(ROOT).parts):
            compile(path.read_text(), str(path), 'exec')
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], cwd=ROOT, check=True)
    node = os.environ.get('ORBITA_NODE') or shutil.which('node')
    if not node:
        raise SystemExit('Node.js 22 ou superior é necessário apenas para verificar o JavaScript.')
    for path in ('extension.js', 'spotify_hook.js'):
        subprocess.run([node, '--check', str(ROOT / path)], check=True)
    subprocess.run([node, str(ROOT / 'tests/test_spotify_hook.cjs')], cwd=ROOT, check=True)
    if shutil.which('desktop-file-validate'):
        subprocess.run(['desktop-file-validate', str(ROOT / 'packaging/io.github.giovannibl13.Orbita.desktop')], check=True)
    print('Código, integrações e arquivo do menu aprovados.')


if __name__ == '__main__':
    main()
