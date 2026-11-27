import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'checkpoint.sh'


class CheckpointTests(unittest.TestCase):
    def test_stage_commits_status_when_optional_glob_has_no_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / 'store'

            def git(*args):
                return subprocess.run(
                    ['git', '-C', str(store), *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            subprocess.run(['git', 'init', '-q', '--bare', str(root / 'origin')], check=True)
            store.mkdir()
            git('init', '-q', '-b', 'data')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                'commit', '--allow-empty', '-qm', 'base')
            git('remote', 'add', 'origin', str(root / 'origin'))
            git('push', '-q', 'origin', 'data')
            (store / 'holders').mkdir()
            (store / 'holders/status.json').write_text('{}')
            (store / 'failed-stage.tmp').write_text('unused')
            command = ['bash', str(SCRIPT), str(store), 'holders status',
                       'holders/status.json', ':(glob)holders/daily/*.json']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'),
                             'holders/status.json')
