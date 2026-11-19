#!/usr/bin/python3
"""Prepara uma cópia local do Spotify com a integração de letras e ritmo do Órbita."""
import argparse
import hashlib
import json
import os
import platform
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import urllib.request

VERSION = '2.46.4'
SHA256 = '61216076ef40eb46e57716b2f68ae9e5281e1c440e67ae34013facdb25300cfd'
URL = f'https://github.com/spicetify/cli/releases/download/v{VERSION}/spicetify-{VERSION}-linux-amd64.tar.gz'


def quoted(value):
    # Desktop Entry não usa um shell para abrir o executável.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'


def systemd_quoted(value):
    text = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$')
    return '"' + text + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, help='usa uma cópia verificada do Spicetify 2.46.4')
    parser.add_argument('--verificar', action='store_true', help='verifica o Spotify sem alterar arquivos')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    user_data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    user_config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    base = user_data / 'orbita-spotify'
    original = Path('/usr/share/spotify')
    if not (original / 'spotify').is_file():
        raise SystemExit('Esta integração foi preparada para o Spotify instalado em /usr/share/spotify.')
    preferences = user_config / 'spotify/prefs'
    if not preferences.is_file():
        raise SystemExit('Abra o Spotify, entre na sua conta e feche o aplicativo antes de conectar o Órbita.')
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise SystemExit('A conexão com o Spotify deste pacote requer Linux x86_64.')
    installed = user_data / 'gnome-shell/extensions/orbita-desktop@local'
    if not (installed / 'metadata.json').is_file() and not args.verificar:
        raise SystemExit('Ative o papel de parede antes de conectar o Spotify.')
    if args.verificar:
        print('Spotify .deb x86_64 e preferências encontrados. Spicetify fixado em ' + VERSION + '.')
        return
    if os.geteuid() == 0:
        raise SystemExit('Execute a conexão com o Spotify na sua conta, sem sudo.')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            executable = (process / 'exe').resolve()
            if executable in (original / 'spotify', base / 'client/spotify'):
                raise SystemExit('Feche o Spotify antes de preparar a conexão. Depois abra-o pelo menu de aplicativos.')
        except OSError:
            continue
    base.mkdir(parents=True, exist_ok=True)
    runtime = base / ('spicetify-' + VERSION)
    if not (runtime / 'spicetify').exists():
        if args.runtime:
            if subprocess.check_output([str(args.runtime / 'spicetify'), '--version'], text=True).strip() != VERSION:
                raise SystemExit('Versão inesperada do Spicetify.')
            shutil.copytree(args.runtime, runtime, dirs_exist_ok=True)
        else:
            archive = base / ('spicetify-' + VERSION + '.tar.gz')
            print('Baixando o Spicetify verificado…', flush=True)
            with urllib.request.urlopen(URL, timeout=30) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
                raise SystemExit('O arquivo recebido não corresponde ao SHA-256 da versão publicada.')
            with tarfile.open(archive) as package:
                package.extractall(runtime, filter='data')
    client = base / 'client'
    if not (client / '.orbita-copy').exists():
        print('Preparando a cópia local do Spotify…', flush=True)
        shutil.copytree(original, client, dirs_exist_ok=True)
        (client / '.orbita-copy').write_text('Spotify com integração local do Órbita\n')
    config_file = user_config / 'orbita-desktop/spotify.json'
    config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if config_file.exists():
        config = json.loads(config_file.read_text())
    else:
        config = {'port': 45739, 'token': secrets.token_hex(32)}
        descriptor = os.open(config_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(config, stream)
    if not re.fullmatch(r'[a-f0-9]{64}', config.get('token', '')) or not 1024 <= int(config.get('port', 0)) <= 65535:
        raise SystemExit('A configuração local do Órbita é inválida. Remova a integração e conecte novamente.')
    config_file.chmod(0o600)
    settings_root = base / 'spicetify-config'
    extensions = settings_root / 'spicetify/Extensions'
    extensions.mkdir(parents=True, exist_ok=True)
    hook = (source / 'spotify_hook.js').read_text().replace('__ORBITA_LOCAL_TOKEN__', config['token'])
    hook = hook.replace('127.0.0.1:45739', '127.0.0.1:' + str(int(config.get('port', 45739))))
    (extensions / 'orbita-lyrics.js').write_text(hook)
    environment = dict(os.environ, XDG_CONFIG_HOME=str(settings_root))
    binary = str(runtime / 'spicetify')
    preferences = user_config / 'spotify/prefs'
    values = ['spotify_path', str(client), 'prefs_path', str(preferences),
              'current_theme', '', 'inject_css', '0', 'replace_colors', '0',
              'overwrite_assets', '0', 'inject_theme_js', '0',
              'check_spicetify_update', '0', 'disable_sentry', '0',
              'disable_ui_logging', '0', 'remove_rtl_rule', '0',
              'expose_apis', '1', 'extensions', 'orbita-lyrics.js']
    subprocess.run([binary, 'config', *values], env=environment, check=True)
    subprocess.run([binary, '-n', 'backup', 'apply'], env=environment, check=True)
    installed = user_data / 'gnome-shell/extensions/orbita-desktop@local'
    installed.mkdir(parents=True, exist_ok=True)
    for name in ['bridge.py', 'lyrics.py', 'rhythm.py', 'artwork.py', 'spotify_receiver.py']:
        shutil.copy2(source / name, installed / name)
    units = user_config / 'systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    unit = ('[Unit]\nDescription=Letras e ritmo do Spotify para o Órbita\nAfter=graphical-session.target\n'
            '\n[Service]\nType=simple\nExecStart=/usr/bin/python3 ' + systemd_quoted(installed / 'spotify_receiver.py') +
            '\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=true\n'
            '\n[Install]\nWantedBy=default.target\n')
    (units / 'orbita-letras.service').write_text(unit)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'orbita-letras.service'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'orbita-letras.service'], check=True)
    applications = user_data / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    desktop = applications / 'spotify.desktop'
    if desktop.exists() and 'X-Orbita-Managed=true' not in desktop.read_text():
        shutil.copy2(desktop, base / 'spotify-desktop-anterior.desktop')
    desktop.write_text('[Desktop Entry]\nType=Application\nName=Spotify\n'
                       'GenericName=Reprodutor de música\nIcon=spotify-client\n'
                       'TryExec=' + str(client / 'spotify') + '\nExec=' + quoted(client / 'spotify').replace('%', '%%') +
                       ' %U\nTerminal=false\nMimeType=x-scheme-handler/spotify;\n'
                       'Categories=Audio;Music;Player;AudioVideo;\nStartupWMClass=spotify\nX-Orbita-Managed=true\n')
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(applications)], check=True)
    print('Integração preparada. O próximo início do Spotify carrega as letras e o ritmo do Órbita.', flush=True)


if __name__ == '__main__':
    main()
