#!/usr/bin/python3
"""Configuração do Órbita pela interface gráfica ou pela linha de comando."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent


def command(script, *arguments):
    return ['/usr/bin/python3', str(ROOT / script), *arguments]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--instalar', action='store_true', help='ativa o papel de parede nesta conta')
    actions.add_argument('--spotify', action='store_true', help='prepara letras e ritmo do Spotify')
    actions.add_argument('--remover', action='store_true', help='remove os dados de instalação desta conta')
    actions.add_argument('--desativar', action='store_true', help='desativa o papel de parede')
    actions.add_argument('--verificar', action='store_true', help='confere a compatibilidade sem instalar')
    actions.add_argument('--versao', action='store_true', help='mostra a versão')
    args = parser.parse_args(argv)
    if args.versao:
        print('Órbita ' + (ROOT / 'VERSION').read_text().strip())
        return 0
    if args.verificar:
        return subprocess.call(command('instalar.py', '--verificar'))
    if os.geteuid() == 0:
        print('Abra o Órbita pela sua conta, sem sudo.', file=sys.stderr)
        return 1
    for flag, script in ((args.instalar, 'instalar.py'), (args.spotify, 'ativar-spotify.py'), (args.remover, 'remover.py')):
        if flag:
            return subprocess.call(command(script))
    if args.desativar:
        return subprocess.call(['gnome-extensions', 'disable', 'orbita-desktop@local'])
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
    except (ImportError, ValueError):
        print('Instale python3-gi e gir1.2-gtk-3.0 para abrir a janela. A opção --instalar funciona pelo terminal.', file=sys.stderr)
        return 1

    class Setup(Gtk.Window):
        def __init__(self):
            super().__init__(title='Órbita — Configurar')
            self.set_default_size(650, 580)
            self.set_border_width(28)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.connect('destroy', self.on_close)
            self.process = None
            self.closed = False
            layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            self.add(layout)
            title = Gtk.Label(label='Sua música, em órbita', xalign=0)
            title.set_markup('<span size="xx-large" weight="bold">Sua música, em órbita</span>')
            layout.pack_start(title, False, False, 0)
            description = Gtk.Label(label='Terra e Lua em movimento, letra e vinil com a capa do álbum.\nSomente na segunda área de trabalho do GNOME 46.', xalign=0)
            description.set_line_wrap(True)
            layout.pack_start(description, False, False, 0)
            self.buttons = []
            for label, scripts in (
                    ('Ativar papel de parede na minha conta', [('instalar.py',)]),
                    ('Conectar letras e ritmo do Spotify', [('instalar.py',), ('ativar-spotify.py',)])):
                button = Gtk.Button(label=label)
                button.set_size_request(-1, 42)
                button.connect('clicked', lambda _button, sequence=scripts: self.start(sequence))
                self.buttons.append(button)
                layout.pack_start(button, False, False, 0)
            note = Gtk.Label(label='Spotify: instale a versão .deb, entre na sua conta e feche o aplicativo antes de conectar.', xalign=0)
            note.set_line_wrap(True)
            layout.pack_start(note, False, False, 0)
            row = Gtk.Box(spacing=10)
            layout.pack_start(row, False, False, 0)
            for label, scripts in (
                    ('Desativar', [('gnome-extensions', 'disable', 'orbita-desktop@local')]),
                    ('Remover da minha conta', [('remover.py',)])):
                button = Gtk.Button(label=label)
                button.connect('clicked', lambda _button, sequence=scripts: self.start(sequence))
                self.buttons.append(button)
                row.pack_start(button, True, True, 0)
            self.status = Gtk.Label(label='Ative o visual e entre novamente na sessão do Zorin.', xalign=0)
            self.status.set_line_wrap(True)
            layout.pack_start(self.status, False, False, 0)
            self.output = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                       wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10)
            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(150)
            scroll.add(self.output)
            layout.pack_start(scroll, True, True, 0)
            self.output.get_buffer().set_text('Versão ' + (ROOT / 'VERSION').read_text().strip() + '\nA instalação é feita somente na sua conta.\nAs outras áreas mantêm o papel de parede atual.')

        def start(self, scripts):
            for button in self.buttons:
                button.set_sensitive(False)
            self.status.set_text('Preparando… A conexão com o Spotify pode levar alguns minutos.')
            self.output.get_buffer().set_text('')
            def run():
                messages = []
                success = True
                try:
                    for parts in scripts:
                        if self.closed:
                            return
                        argv = command(*parts) if parts[0].endswith('.py') else list(parts)
                        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        output, _ = self.process.communicate()
                        messages.append(output)
                        if self.process.returncode:
                            success = False
                            break
                except OSError as error:
                    messages.append(str(error))
                    success = False
                finally:
                    self.process = None
                GLib.idle_add(self.finish, success, '\n'.join(messages))
            threading.Thread(target=run, daemon=True).start()

        def finish(self, success, output):
            if self.closed:
                return GLib.SOURCE_REMOVE
            for button in self.buttons:
                button.set_sensitive(True)
            self.status.set_text('Concluído. Confira as instruções abaixo.' if success else 'Não foi possível concluir. Confira a mensagem abaixo.')
            self.output.get_buffer().set_text(output.strip())
            return GLib.SOURCE_REMOVE

        def on_close(self, *_):
            self.closed = True
            if self.process and self.process.poll() is None:
                self.process.terminate()
            Gtk.main_quit()

    window = Setup()
    window.show_all()
    Gtk.main()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
