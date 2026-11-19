"""Instala, atualiza e remove em diretórios XDG temporários, sem tocar na conta."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UUID = 'orbita-desktop@local'


def main():
    with tempfile.TemporaryDirectory(prefix='orbita-conta-') as directory:
        base = Path(directory)
        account = base / 'conta com espaço'
        for variable, folder in [('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:
            os.environ[variable] = str(account / folder)
        os.environ['GSETTINGS_BACKEND'] = 'keyfile'
        binary = base / 'bin'
        binary.mkdir()
        for name, body in [('gnome-shell', '#!/bin/sh\necho "GNOME Shell 46.0"\n'),('gnome-extensions','#!/bin/sh\nexit 0\n')]:
            path = binary / name
            path.write_text(body)
            path.chmod(0o755)
        os.environ['PATH'] = str(binary) + ':' + os.environ.get('PATH','')
        from gi.repository import Gio
        settings = Gio.Settings.new('org.gnome.shell')
        settings.set_strv('enabled-extensions', ['outra-extensao@teste'])
        settings.set_strv('disabled-extensions', ['desativada@teste'])
        Gio.Settings.sync()
        payload = base / 'pacote somente leitura'
        payload.mkdir()
        names = ('instalar.py','remover.py','VERSION','README.md','LICENSE','THIRD_PARTY_NOTICES.md','metadata.json','extension.js','bridge.py','lyrics.py','rhythm.py','artwork.py','spotify_receiver.py','stylesheet.css','moon-style.json','terra.jpg','lua.jpg')
        for name in names:
            shutil.copy2(ROOT/name,payload/name)
        shutil.copytree(ROOT/'licenses',payload/'licenses')
        for path in payload.rglob('*'):
            path.chmod(0o555 if path.is_dir() else 0o444)
        payload.chmod(0o555)
        try:
            def run(script):
                result = subprocess.run([sys.executable,str(payload/script)],text=True,capture_output=True)
                assert result.returncode == 0, result.stdout + result.stderr
            run('instalar.py')
            target = Path(os.environ['XDG_DATA_HOME'])/'gnome-shell/extensions'/UUID
            assert (target/'extension.js').is_file()
            assert not (payload/'instalacao.json').exists()
            state = Path(os.environ['XDG_STATE_HOME'])/'orbita-desktop/instalacao.json'
            assert state.is_file() and state.stat().st_mode & 0o777 == 0o600
            style = json.loads((target/'moon-style.json').read_text())
            style['earthFloatX'] = 23
            (target/'moon-style.json').write_text(json.dumps(style))
            run('instalar.py')
            assert json.loads((target/'moon-style.json').read_text())['earthFloatX'] == 23
            cached = Path(os.environ['XDG_CACHE_HOME'])/'orbita-desktop'
            cached.mkdir(parents=True)
            (cached/'teste.txt').write_text('cache de teste')
            run('remover.py')
            assert not target.exists() and not cached.exists() and not state.exists()
            settings.sync()
            assert settings.get_strv('enabled-extensions') == ['outra-extensao@teste']
            assert settings.get_strv('disabled-extensions') == ['desativada@teste']
            print('Instalação aprovada: pacote somente leitura, XDG com espaço, atualização e remoção isoladas.')
        finally:
            payload.chmod(0o755)
            for path in payload.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == '__main__':
    main()
