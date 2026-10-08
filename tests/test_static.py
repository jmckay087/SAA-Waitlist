import tempfile
import unittest
from pathlib import Path

from build_static import build


class StaticBuildTest(unittest.TestCase):
    def test_build_is_repeatable_and_contains_only_public_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'website'
            build(output)
            first = (output / 'index.html').read_text()
            build(output)
            self.assertEqual(first, (output / 'index.html').read_text())
            self.assertIn('./static/local-store.js', first)
            self.assertIn('id="default-schedule"', first)
            self.assertIn('id="restore-file"', first)
            self.assertNotIn('/static/', first.replace('./static/', ''))
            self.assertNotIn('{{', first)
            self.assertNotIn('{%', first)
            self.assertNotIn('id="logout"', first)
            self.assertEqual({p.name for p in output.iterdir()}, {'index.html', 'static', '.nojekyll', '.saa-static-build'})
            self.assertFalse(any(p.suffix in {'.sqlite3', '.py', '.csv'} or p.name == '.session-key' for p in output.rglob('*')))

    def test_build_refuses_to_replace_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            customer_file = output / 'keep-me.txt'
            customer_file.write_text('existing file')
            with self.assertRaises(ValueError):
                build(output)
            self.assertEqual(customer_file.read_text(), 'existing file')
