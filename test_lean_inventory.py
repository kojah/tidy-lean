"""Opt-in native probe regression; run under agent-test with PAPER_CHECK_LEAN_TESTS=1."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from check_paper import LAKE, PROOFS, HERE
from paper_orphans import parse_inventory, audit, source_inventory


@unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean probe is opt-in')
class NativeInventoryTests(unittest.TestCase):
    def test_elaborated_bodies_private_helpers_and_disconnected_theorem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'DeadlockProofs' / 'OrphanFixture.lean'
            source.parent.mkdir()
            source.write_text('''import Lean
import Mathlib.Lean.Expr.Basic
namespace OrphanFixture
theorem helper : True := True.intro
def bridge : True := helper
theorem paper_root : True := bridge
theorem type_helper : True := True.intro
theorem type_root : type_helper = type_helper := rfl
private theorem private_helper : True := True.intro
private theorem unused_private : True := True.intro
theorem with_private : True := private_helper
theorem orphan : True := True.intro
def unused_definition : Nat := 0
structure UnusedStructure where
  field : Nat
mutual
inductive First where
  | fromSecond : Second → First
inductive Second where
  | base
  | fromFirst : First → Second
end
@[ext] structure UsedStructure where
  field : Nat
theorem uses_structure (s : UsedStructure) : s.field = s.field := rfl
@[simp] theorem erased_helper : (0 : Nat) + 0 = 0 := rfl
theorem uses_erased_helper : (0 : Nat) + 0 = 0 := by simp only [erased_helper]
end OrphanFixture
''')
            build = subprocess.run([LAKE, 'env', 'lean', '-R', str(root),
                                    '-o', str(source.with_suffix('.olean')),
                                    '-i', str(source.with_suffix('.ilean')), str(source)],
                                   cwd=PROOFS, capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            probe = root / 'Probe.lean'
            probe.write_text('import DeadlockProofs.OrphanFixture\n'
                             + Path(HERE, 'Dump.lean').read_text().replace('import Lean\n', '')
                             + '\n#paper_inventory\n')
            path = subprocess.run([LAKE, 'env', 'printenv', 'LEAN_PATH'], cwd=PROOFS,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(path.returncode, 0, path.stderr)
            # Prepend after lake sets its paths: its existing package directory
            # otherwise shadows the temporary module of the same package.
            search = str(root) + os.pathsep + path.stdout.strip()
            run = subprocess.run([LAKE, 'env', 'env', 'LEAN_PATH=' + search,
                                  'lean', '-R', str(root), str(probe)], cwd=PROOFS,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            modules, nodes = parse_inventory(run.stdout + run.stderr)
            nodes = source_inventory(root, modules, nodes, root)
            report = audit(nodes, modules, {'OrphanFixture.paper_root', 'OrphanFixture.with_private',
                                           'OrphanFixture.type_root', 'OrphanFixture.uses_structure',
                                           'OrphanFixture.uses_erased_helper'},
                           {'DeadlockProofs.OrphanFixture'})
            self.assertIn('OrphanFixture.orphan', report['orphaned_proofs'])
            self.assertEqual(len(report['orphaned_proofs']), 2)
            self.assertTrue(any('unused_private' in name for name in report['orphaned_proofs']))
            self.assertEqual(report['unused_orphaned_proofs'], report['orphaned_proofs'])
            self.assertIn('OrphanFixture.helper', report['paper_connected'])
            self.assertIn('OrphanFixture.type_helper', report['paper_connected'])
            self.assertIn('OrphanFixture.erased_helper', report['paper_connected'])
            self.assertIn('OrphanFixture.unused_definition', report['orphaned_declarations'])
            self.assertIn('OrphanFixture.UnusedStructure', report['orphaned_declarations'])
            self.assertIn('OrphanFixture.First', report['orphaned_declarations'])
            self.assertIn('OrphanFixture.Second', report['orphaned_declarations'])
            self.assertEqual(report['declaration_kinds']['OrphanFixture.UnusedStructure'], 'structure')
            self.assertNotIn('OrphanFixture.UsedStructure', report['orphaned_declarations'])
            self.assertNotIn('OrphanFixture.UsedStructure.ext', report['orphaned_declarations'])
            private = [name for name in report['paper_connected'] if 'private_helper' in name]
            self.assertEqual(len(private), 1)


if __name__ == '__main__':
    unittest.main()
