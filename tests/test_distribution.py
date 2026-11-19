import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_readonly_install_update_remove(self):
        if not shutil.which('dbus-run-session'):
            self.skipTest('dbus-run-session não instalado')
        result = subprocess.run(['dbus-run-session','--',sys.executable,str(ROOT/'tests/smoke_install.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_spotify_pin_and_path_quoting(self):
        spec=importlib.util.spec_from_file_location('spotify_setup',ROOT/'ativar-spotify.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.VERSION,'2.46.4')
        self.assertEqual(len(module.SHA256),64)
        self.assertEqual(module.systemd_quoted('/tmp/conta com espaço/arquivo.py'),'"/tmp/conta com espaço/arquivo.py"')
        self.assertEqual(module.systemd_quoted('/tmp/100%/$teste.py'),'"/tmp/100%%/$$teste.py"')
        self.assertEqual(module.quoted('/tmp/conta com espaço/spotify'),'"/tmp/conta com espaço/spotify"')


if __name__ == '__main__':
    unittest.main()
