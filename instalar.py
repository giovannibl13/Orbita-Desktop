#!/usr/bin/python3
"""Instala o papel de parede somente na conta que executar este programa."""
import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

UUID = 'orbita-desktop@local'
FILES = ('metadata.json', 'extension.js', 'bridge.py', 'lyrics.py', 'rhythm.py',
         'artwork.py', 'spotify_receiver.py', 'stylesheet.css', 'moon-style.json',
         'terra.jpg', 'lua.jpg', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
         'licenses/CC-BY-SA-3.0.txt')


def verify(source):
    errors = []
    try:
        version = subprocess.check_output(['gnome-shell', '--version'], text=True, stderr=subprocess.STDOUT)
        if not re.search(r'\b46(?:\.|\s|$)', version):
            errors.append('Este pacote requer GNOME Shell 46, como o Zorin OS 18.')
    except (OSError, subprocess.CalledProcessError):
        errors.append('GNOME Shell não encontrado.')
    if not shutil.which('pw-cat'):
        errors.append('Instale pipewire-bin para capturar o áudio de saída.')
    if not ctypes.util.find_library('fftw3'):
        errors.append('Instale libfftw3-double3 para analisar o áudio.')
    try:
        import gi
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import Gio, GLib, GdkPixbuf
        if Gio.SettingsSchemaSource.get_default().lookup('org.gnome.shell', True) is None:
            errors.append('Os esquemas de configuração do GNOME não estão disponíveis.')
    except (ImportError, ValueError):
        errors.append('Instale python3-gi e gir1.2-gdkpixbuf-2.0.')
    for name in FILES:
        if not (source / name).is_file():
            errors.append('Arquivo ausente no pacote: ' + name)
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verificar', action='store_true', help='confere requisitos sem instalar')
    parser.add_argument('--restaurar-aparencia', action='store_true', help='restaura os ajustes visuais do pacote')
    args = parser.parse_args(argv)
    source = Path(__file__).resolve().parent
    errors = verify(source)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    if args.verificar:
        print('Requisitos conferidos: GNOME 46, PipeWire, FFTW e arquivos do pacote.')
        return 0
    if os.geteuid() == 0:
        print('Execute a ativação na sua conta, sem sudo. O pacote .deb instala as dependências separadamente.', file=sys.stderr)
        return 1
    from gi.repository import Gio, GLib
    destination = Path(GLib.get_user_data_dir()) / 'gnome-shell' / 'extensions' / UUID
    old_main = destination / 'extension.js'
    changed = not old_main.exists() or hashlib.sha256(old_main.read_bytes()).digest() != hashlib.sha256((source / 'extension.js').read_bytes()).digest()
    destination.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = destination / name
        if name == 'moon-style.json' and target.exists() and not args.restaurar_aparencia:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.orbita-', dir=target.parent)
        os.close(descriptor)
        try:
            shutil.copyfile(source / name, temporary)
            os.chmod(temporary, 0o644)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    settings = Gio.Settings.new('org.gnome.shell')
    enabled = settings.get_strv('enabled-extensions')
    if UUID not in enabled:
        settings.set_strv('enabled-extensions', enabled + [UUID])
    settings.set_strv('disabled-extensions', [item for item in settings.get_strv('disabled-extensions') if item != UUID])
    Gio.Settings.sync()
    # Uma extensão ainda não carregada ficará disponível no próximo login.
    subprocess.run(['gnome-extensions', 'enable', UUID], capture_output=True)
    directory = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'orbita-desktop'
    directory.mkdir(parents=True, exist_ok=True)
    state = {'version': (source / 'VERSION').read_text().strip(), 'uuid': UUID,
             'destination': str(destination), 'workspace': 2, 'new_session_required': changed}
    descriptor = os.open(directory / 'instalacao.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
    print('Órbita ativado na sua conta. O visual aparece somente na segunda área de trabalho.')
    print('Saia da sessão do Zorin e entre novamente para carregar o desenho atualizado.' if changed else
          'Abra a segunda área de trabalho. Os ajustes de aparência são aplicados automaticamente.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
