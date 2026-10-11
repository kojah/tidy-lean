"""The complete audit must include each semantic library, but not tooling."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_paper
from paper_orphans import source_modules


class LibraryRootsTests(unittest.TestCase):
    def test_separate_library_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {'Proofs'}
            (root / 'Proofs.lean').write_text('')
            for library in ('Support', 'Framework', 'PointsTo', 'DeadlockProofs'):
                (root / library).mkdir()
                (root / (library + '.lean')).write_text('')
                (root / library / 'Example.lean').write_text('')
                expected.update({library, library + '.Example'})
            (root / 'formulas').mkdir()
            (root / 'formulas' / 'Tool.lean').write_text('')
            self.assertEqual(source_modules(root), expected)

    def test_umbrella_and_legacy_entry_points(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(check_paper, 'PROOFS', directory):
                self.assertTrue(check_paper.probe_source([], False).startswith('import DeadlockProofs\n'))
                Path(directory, 'Proofs.lean').write_text('')
                self.assertTrue(check_paper.probe_source([], False).startswith('import Proofs\n'))
