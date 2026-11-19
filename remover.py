#!/usr/bin/python3
"""Remove a instalação e os dados do Órbita somente da conta atual."""
import os
from pathlib import Path
import shutil
import subprocess
from gi.repository import Gio, GLib

UUID = 'orbita-desktop@local'


def main():
    if os.geteuid() == 0:
        raise SystemExit('Remova a ativação pela sua conta, sem sudo.')
    user_data = Path(GLib.get_user_data_dir())
    user_config = Path(GLib.get_user_config_dir())
    spotify_copy = user_data / 'orbita-spotify'
    client_binary = spotify_copy / 'client/spotify'
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / 'exe').resolve() == client_binary:
                raise SystemExit('Feche o Spotify antes de remover a integração do Órbita.')
        except OSError:
            continue
    unit = user_config / 'systemd/user/orbita-letras.service'
    if unit.exists() and 'spotify_receiver.py' in unit.read_text():
        subprocess.run(['systemctl', '--user', 'disable', '--now', 'orbita-letras.service'], capture_output=True)
        unit.unlink()
        subprocess.run(['systemctl', '--user', 'daemon-reload'], capture_output=True)
    desktop = user_data / 'applications/spotify.desktop'
    if desktop.exists() and 'X-Orbita-Managed=true' in desktop.read_text():
        previous = spotify_copy / 'spotify-desktop-anterior.desktop'
        if previous.exists():
            shutil.copy2(previous, desktop)
        else:
            desktop.unlink()
        if shutil.which('update-desktop-database'):
            subprocess.run(['update-desktop-database', str(desktop.parent)], capture_output=True)
    if (spotify_copy / 'client/.orbita-copy').exists():
        shutil.rmtree(spotify_copy)
    (user_config / 'orbita-desktop/spotify.json').unlink(missing_ok=True)
    subprocess.run(['gnome-extensions', 'disable', UUID], capture_output=True)
    settings = Gio.Settings.new('org.gnome.shell')
    for key in ('enabled-extensions', 'disabled-extensions'):
        settings.set_strv(key, [item for item in settings.get_strv(key) if item != UUID])
    Gio.Settings.sync()
    paths = [user_data / 'gnome-shell/extensions' / UUID,
             Path(GLib.get_user_cache_dir()) / 'orbita-desktop',
             Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'orbita-desktop']
    for directory in paths:
        if directory.exists():
            shutil.rmtree(directory)
    print('Órbita removido da sua conta. O papel de parede das demais áreas foi preservado.')
    print('Para remover também o pacote do sistema, use: sudo apt remove orbita-desktop')


if __name__ == '__main__':
    main()
