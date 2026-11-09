# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Hosted links must resolve within the tracked, case-sensitive Git tree."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[1] / 'tools/xcheck-links.py'


class HostedLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hosted links ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'consumer'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'README.md').write_text('')
        (self.root / 'doc').mkdir()
        (self.root / 'doc/Guide.md').write_text('# Guide\n## Build steps\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)

    def check_links(self, body, hosted=True):
        (self.root / 'README.md').write_text(body)
        return subprocess.run([sys.executable, CHECKER, '--root', self.root,
                               '--anchors', *(['--github-hosted'] if hosted else []),
                               'README.md'], capture_output=True, text=True)

    def test_existing_sibling_link_fails_in_hosted_mode(self):
        sibling = self.root.parent / 'shared'
        sibling.mkdir()
        (sibling / 'README.md').write_text('# Shared\n')
        body = '[shared](../shared/README.md)\n'
        self.assertEqual(self.check_links(body, hosted=False).returncode, 0)
        self.assertNotEqual(self.check_links(body).returncode, 0)

    def test_tracked_files_directories_and_anchors_pass(self):
        result = self.check_links('[guide](doc/Guide.md#build-steps)\n[dir](doc/)\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.check_links('[guide](doc/Guide.md#absent)').returncode, 0)

    def test_local_untracked_artifact_is_not_a_public_target(self):
        (self.root / 'generated.md').write_text('# Generated\n')
        self.assertNotEqual(self.check_links('[generated](generated.md)').returncode, 0)

    def test_wrong_case_is_rejected_on_every_host(self):
        self.assertNotEqual(self.check_links('[guide](doc/guide.md)').returncode, 0)


if __name__ == '__main__':
    unittest.main()
