#!/usr/bin/python3
"""Gera o .deb, o pacote portátil e o código-fonte para a Release."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'VERSION',
              '.gitignore', '.gitattributes', 'extension.js', 'metadata.json',
              'stylesheet.css', 'moon-style.json', 'terra.jpg', 'lua.jpg', 'artwork.py',
              'bridge.py', 'lyrics.py', 'rhythm.py', 'spotify_receiver.py', 'spotify_hook.js',
              'instalar.py', 'instalar.sh', 'ativar-spotify.py', 'remover.py', 'configurar.py')
DIRECTORIES = ('licenses', 'docs', 'packaging', 'scripts', 'tests', '.github')
EXECUTABLES = {'instalar.sh', 'packaging/orbita-desktop'}


def source_files():
    files = [ROOT / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return sorted(files)


def verify(files):
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('VERSION precisa conter uma versão como 1.0.0.')
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Arquivo ausente ou link inesperado: ' + str(path))
        if path.name in ('spotify.json', 'instalacao.json', '.env') or path.suffix in ('.log', '.pyc'):
            raise ValueError('Arquivo local fora da distribuição: ' + path.name)
        if path.suffix not in ('.jpg', '.png'):
            data = path.read_text()
            if re.search('/' + 'home' + r'/[^/\s]+/', data):
                raise ValueError('Caminho pessoal encontrado: ' + str(path.relative_to(ROOT)))
            if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})', data):
                raise ValueError('Credencial encontrada: ' + str(path.relative_to(ROOT)))
    if "const token = '__ORBITA_LOCAL_TOKEN__';" not in (ROOT / 'spotify_hook.js').read_text():
        raise ValueError('O conector público deve conter somente o marcador da chave local.')
    for required in ('licenses/CC-BY-SA-3.0.txt', 'docs/previa.png'):
        if not (ROOT / required).is_file():
            raise ValueError('Arquivo de distribuição ausente: ' + required)
    return version


def epoch():
    if os.environ.get('SOURCE_DATE_EPOCH'):
        return int(os.environ['SOURCE_DATE_EPOCH'])
    result = subprocess.run(['git', '-C', str(ROOT), 'log', '-1', '--format=%ct'], capture_output=True, text=True)
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else int((ROOT / 'VERSION').stat().st_mtime)


def mode(path):
    return 0o755 if path.relative_to(ROOT).as_posix() in EXECUTABLES else 0o644


def payload(files):
    return [p for p in files if p.relative_to(ROOT).parts[0] not in ('scripts', 'tests', '.github', 'packaging') and p.name not in ('.gitignore', '.gitattributes')]


def build_deb(files, version, output, stamp):
    if not shutil.which('dpkg-deb'):
        raise SystemExit('Instale dpkg para gerar o pacote .deb.')
    with tempfile.TemporaryDirectory(prefix='orbita-build-') as directory:
        stage = Path(directory)
        app = stage / 'usr/share/orbita-desktop'
        for path in payload(files):
            target = app / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(mode(path))
        for source, target in (
                ('packaging/orbita-desktop', 'usr/bin/orbita-desktop'),
                ('packaging/io.github.giovannibl13.Orbita.desktop', 'usr/share/applications/io.github.giovannibl13.Orbita.desktop'),
                ('packaging/orbita-desktop.svg', 'usr/share/icons/hicolor/scalable/apps/orbita-desktop.svg')):
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)
            destination.chmod(mode(ROOT / source))
        doc = stage / 'usr/share/doc/orbita-desktop'
        doc.mkdir(parents=True)
        (doc / 'copyright').write_text((ROOT / 'THIRD_PARTY_NOTICES.md').read_text() + '\n\n' + (ROOT / 'LICENSE').read_text() + '\n\n' + (ROOT / 'licenses/CC-BY-SA-3.0.txt').read_text())
        control = stage / 'DEBIAN'
        control.mkdir()
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        (control / 'control').write_text((ROOT / 'packaging/control.in').read_text().replace('@VERSION@', version).replace('@SIZE@', str((size + 1023) // 1024)))
        sums = []
        for path in sorted((stage / 'usr').rglob('*')):
            if path.is_file():
                sums.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + path.relative_to(stage).as_posix())
        (control / 'md5sums').write_text('\n'.join(sums) + '\n')
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
            elif path.parent == control:
                path.chmod(0o644)
            os.utime(path, (stamp, stamp))
        os.utime(stage, (stamp, stamp))
        destination = output / f'orbita-desktop_{version}_all.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--build', str(stage), str(destination)], check=True,
                       env=dict(os.environ, SOURCE_DATE_EPOCH=str(stamp)))
        return destination


def build_portable(files, version, output, stamp):
    destination = output / f'orbita-desktop-{version}-portatil.tar.gz'
    with destination.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=stamp) as compressed, tarfile.open(fileobj=compressed, mode='w') as archive:
        for path in payload(files):
            info = archive.gettarinfo(str(path), arcname=f'orbita-desktop-{version}/' + path.relative_to(ROOT).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = stamp
            info.mode = mode(path)
            with path.open('rb') as source:
                archive.addfile(info, source)
    return destination


def build_source(files, version, output, stamp):
    destination = output / f'orbita-desktop-{version}-codigo-fonte.zip'
    date = time.gmtime(max(stamp, 315532800))[:6]
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            info = zipfile.ZipInfo(f'orbita-desktop-{version}/' + path.relative_to(ROOT).as_posix(), date_time=date)
            info.create_system = 3
            info.external_attr = (0o100000 | mode(path)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    files = source_files()
    version = verify(files)
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = epoch()
    artifacts = [build_deb(files, version, args.output, stamp),
                 build_portable(files, version, args.output, stamp),
                 build_source(files, version, args.output, stamp)]
    (args.output / 'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in artifacts))
    print('Pacotes gerados e conferidos, sem dados locais:')
    for path in artifacts:
        print(f'{path.name} ({path.stat().st_size / 1024 / 1024:.1f} MiB)')


if __name__ == '__main__':
    main()
