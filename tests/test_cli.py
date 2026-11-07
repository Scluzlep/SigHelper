"""Integration tests using throwaway keystores and fake gh; no real secrets uploaded."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'android-sig'
REPO = 'octocat/demo-app'


@unittest.skipUnless(shutil.which('keytool') and shutil.which('openssl'), 'keytool and openssl required')
class AndroidSigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='android-sig-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'signing'
        self.env = os.environ.copy()
        self.env['ANDROID_SIG_HOME'] = str(self.home)
        self.env.pop('ANDROID_SIG_PASSWORD', None)

    def run_cli(self, *args, success=True):
        p = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if success:
            self.assertEqual(p.returncode, 0, f'args={args}\nstdout={p.stdout}\nstderr={p.stderr}')
        else:
            self.assertNotEqual(p.returncode, 0, f'expected failure: {args}')
        return p

    def make_key(self):
        self.run_cli('gen', REPO, '--local-only')
        folder = self.home / 'demo-app-signing'
        return folder, (folder / 'release.p12').read_bytes()

    def test_help(self):
        self.assertIn('adopt', self.run_cli('help').stdout)
        self.assertIn('已有', self.run_cli('help', 'gen').stdout)
        self.assertIn('Usage', self.run_cli('--help').stdout.title())

    def test_create_verify_and_idempotence(self):
        folder, original = self.make_key()
        self.assertEqual((folder / 'release.p12').stat().st_mode & 0o777, 0o600)
        self.assertEqual((folder / 'release.p12.password.txt').stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        info = json.loads(self.run_cli('veri', REPO, '--json').stdout)
        self.assertEqual(info['certificate']['alias'], 'release')
        self.assertTrue(info['bound'])
        self.assertEqual(info['certificate']['key_size'], 3072)
        self.run_cli('gen', REPO, '--local-only')
        self.assertEqual((folder / 'release.p12').read_bytes(), original)
        self.assertIn('VALID', self.run_cli('list').stdout)
        self.assertEqual(json.loads(self.run_cli('list', '--json').stdout)[0]['repository'], REPO)

    def test_adopt_does_not_mutate_existing_key(self):
        folder, original = self.make_key()
        original_password = (folder / 'release.p12.password.txt').read_bytes()
        (folder / 'metadata.json').unlink()
        self.assertIn('UNBOUND', self.run_cli('list').stdout)
        self.run_cli('gen', REPO, '--local-only', success=False)
        self.run_cli('adopt', REPO)
        self.assertEqual((folder / 'release.p12').read_bytes(), original)
        self.assertEqual((folder / 'release.p12.password.txt').read_bytes(), original_password)
        self.assertEqual(json.loads((folder / 'metadata.json').read_text())['adopted'], True)
        self.assertEqual(json.loads(self.run_cli('veri', REPO, '--json').stdout)['bound'], True)

    def test_prevent_cross_repo_and_corruption(self):
        folder, _ = self.make_key()
        self.run_cli('veri', 'another-owner/demo-app', success=False)
        (folder / 'release.p12.password.txt').write_text('passwd=incorrect-password\n')
        self.run_cli('veri', REPO, success=False)
        self.run_cli('gen', REPO, '--local-only', success=False)

    def test_invalid_names(self):
        self.run_cli('gen', 'not-owner-repo', '--local-only', success=False)
        self.run_cli('gen', REPO, '../escape', '--local-only', success=False)
        self.run_cli('gen', REPO, 'foo/bar', '--local-only', success=False)
        self.assertFalse((Path(self.tmp.name) / 'escape-signing').exists())

    def test_gh_sync_with_stub(self):
        bindir = Path(self.tmp.name) / 'bin'
        bindir.mkdir()
        log = Path(self.tmp.name) / 'remote-secret-names.txt'
        gh = bindir / 'gh'
        gh.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ['repo', 'view']:
    print('octocat/demo-app')
elif args[:2] == ['secret', 'list']:
    print(os.environ.get('FAKE_GH_EXISTING',''))
elif args[:2] == ['secret', 'set']:
    value = sys.stdin.buffer.read()
    if not value: sys.exit(8)
    with open(os.environ['FAKE_GH_LOG'], 'a') as f:
        f.write(args[2] + '\\n')
else:
    sys.exit(9)
''')
        gh.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env.get('PATH', '')
        self.env['FAKE_GH_LOG'] = str(log)
        self.env['FAKE_GH_EXISTING'] = 'SIGNING_PASSWORD'
        self.run_cli('gen', REPO, success=False)
        self.assertFalse((self.home / 'demo-app-signing').exists())
        self.env.pop('FAKE_GH_EXISTING')
        self.run_cli('gen', REPO)
        self.assertEqual(log.read_text().splitlines(), [
            'SIGNING_KEYSTORE_BASE64', 'SIGNING_PASSWORD',
            'SIGNING_KEY_PASSWORD', 'SIGNING_KEY_ALIAS'])
        self.run_cli('veri', REPO, '--remote', success=False)
        self.env['FAKE_GH_EXISTING'] = '\n'.join([
            'SIGNING_KEYSTORE_BASE64', 'SIGNING_PASSWORD',
            'SIGNING_KEY_PASSWORD', 'SIGNING_KEY_ALIAS'])
        self.run_cli('veri', REPO, '--remote')


if __name__ == '__main__':
    unittest.main()