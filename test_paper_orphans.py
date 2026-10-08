import json
import os
import tempfile
import unittest
from pathlib import Path
from paper_orphans import audit, parse_inventory, reachable, source_inventory


def node(name, dependencies=(), proof=True, module='DeadlockProofs.Core', authored=True):
    return dict(name=name, dependencies=list(dependencies), proof=proof,
                module=module, line=1, authored=authored,
                kind='theorem' if proof else 'definition')


class OrphanTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_dependency_closure_keeps_indirect_helpers_and_definitions(self):
        nodes = {n['name']: n for n in [node('root', ['def']), node('def', ['helper'], False),
                                      node('helper', ['Mathlib.foo']), node('orphan')]}
        report = audit(nodes, {'DeadlockProofs.Core'}, {'root'}, {'DeadlockProofs.Core'})
        self.assertEqual(report['orphaned_proofs'], ['orphan'])
        self.assertEqual(set(report['paper_connected']), {'root', 'def', 'helper'})

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_direction_is_not_reversed(self):
        nodes = {n['name']: n for n in [node('root'), node('unused_corollary', ['root'])]}
        self.assertEqual(audit(nodes, set(), {'root'}, set())['orphaned_proofs'], ['unused_corollary'])

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_cycles_terminate_and_generated_nodes_bridge(self):
        nodes = {n['name']: n for n in [node('root', ['generated']), node('generated', ['helper'], False),
                                      node('helper', ['generated'])]}
        self.assertEqual(reachable(nodes, {'root'}), set(nodes))

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_unused_orphans_distinguish_disconnected_helpers_and_cycles(self):
        nodes = {n['name']: n for n in [node('root'), node('unused', ['helper']),
                                      node('helper'), node('left', ['right']),
                                      node('right', ['left']), node('self', ['self'])]}
        report = audit(nodes, set(), {'root'}, set())
        self.assertEqual(report['proof_inventory'], sorted(nodes))
        self.assertEqual(report['unused_orphaned_proofs'], ['self', 'unused'])
        self.assertEqual(report['orphan_dependents']['helper'], ['unused'])
        self.assertEqual(report['dependencies']['left'], ['right'])
        self.assertEqual(report['orphaned_proofs'], ['helper', 'left', 'right', 'self', 'unused'])

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_standalone_root_has_reason_and_keeps_helpers(self):
        nodes = {n['name']: n for n in [node('control', ['helper']), node('helper')]}
        exceptions = {'roots': {'control': 'Independent semantic regression control.'}}
        report = audit(nodes, set(), set(), set(), exceptions)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['orphaned_declarations'], ['control', 'helper'])
        self.assertEqual(report['retained_orphans'], ['control', 'helper'])
        self.assertTrue(audit(nodes, set(), {'control'}, set(), exceptions)['errors'])
        with self.assertRaises(ValueError):
            audit(nodes, set(), set(), set(), {'roots': {'control': ' '}})
        self.assertTrue(audit(nodes, set(), set(), set(), {'roots': {'typo': 'reason'}})['errors'])
        generated = {'generated': node('generated', authored=False)}
        self.assertTrue(audit(generated, set(), set(), set(),
                              {'roots': {'generated': 'reason'}})['errors'])

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_unimported_sources_and_stale_exclusions(self):
        report = audit({}, {'DeadlockProofs.Core'}, set(), {'DeadlockProofs.Core', 'DeadlockProofs.Unbuilt'})
        self.assertEqual(report['unimported_modules'], ['DeadlockProofs.Unbuilt'])
        exceptions = {'modules': {'DeadlockProofs.Unbuilt': 'Archived optional experiment.'}}
        self.assertEqual(audit({}, set(), set(), {'DeadlockProofs.Unbuilt'}, exceptions)['errors'], [])
        self.assertTrue(audit({}, {'DeadlockProofs.Unbuilt'}, set(), {'DeadlockProofs.Unbuilt'}, exceptions)['errors'])
        self.assertTrue(audit({}, set(), set(), set(), exceptions)['errors'])

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_authored_definitions_and_structures_are_pruning_units(self):
        nodes = {n['name']: n for n in [node('root', ['Used']), node('Used', proof=False),
                                      node('unused_def', proof=False), node('Unused', proof=False),
                                      node('Unused.field', proof=False, authored=False),
                                      node('Unused.ext', authored=False)]}
        report = audit(nodes, set(), {'root'}, set())
        self.assertEqual(report['orphaned_declarations'], ['Unused', 'unused_def'])
        self.assertEqual(report['orphaned_proofs'], [])
        self.assertTrue(report['errors'])

    def test_source_index_adds_erased_references_and_excludes_generated_nodes(self):
        module = 'DeadlockProofs.Core'
        nodes = {n['name']: n for n in [node('root'), node('helper'), node('Generated.ext')]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'DeadlockProofs/Core.lean'
            source.parent.mkdir()
            source.write_text('theorem helper : True := True.intro\n')
            index = source.with_suffix('.ilean')
            data = dict(version=5, module=module, decls={'root': [], 'helper': []},
                        references={json.dumps({'c': {'m': module, 'n': 'helper'}}):
                                    {'usages': [[0, 0, 0, 1, 'root']]}})
            index.write_text(json.dumps(data))
            enriched = source_inventory(root, {module}, nodes, root)
            self.assertEqual(enriched['root']['dependencies'], ['helper'])
            self.assertEqual(enriched['root']['source_dependencies'], ['helper'])
            self.assertFalse(enriched['Generated.ext']['authored'])
            data['version'] = 4
            index.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                source_inventory(root, {module}, nodes, root)
            data['version'] = 5
            data['decls']['unknown'] = []
            index.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'missing from environment'):
                source_inventory(root, {module}, nodes, root)
            os.utime(source, ns=(index.stat().st_mtime_ns + 1, index.stat().st_mtime_ns + 1))
            with self.assertRaisesRegex(ValueError, 'stale'):
                source_inventory(root, {module}, nodes, root)
            source.unlink()
            with self.assertRaisesRegex(ValueError, 'missing'):
                source_inventory(root, {module}, nodes, root)

    def test_inventory_rejects_missing_end_and_duplicate_nodes(self):
        header = '@@INVENTORY_BEGIN ["DeadlockProofs.Core"]\n'
        record = '@@NODE ' + json.dumps(node('root')) + '\n'
        end = '@@INVENTORY_END\n'
        modules, nodes = parse_inventory(header + record + end)
        self.assertEqual(modules, {'DeadlockProofs.Core'})
        self.assertEqual(set(nodes), {'root'})
        for output in [header + record, header + record + record + end, record + end,
                       header + end + record, header + header + end, header + end + end]:
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_inventory(output)

    def test_invalid_inventory_schema(self):
        for entry in [node('root') | {'dependencies': 'wrong'}, node('root') | {'proof': 1}]:
            with self.assertRaises(ValueError):
                parse_inventory('@@INVENTORY_BEGIN ["DeadlockProofs.Core"]\n@@NODE '
                                + json.dumps(entry) + '\n@@INVENTORY_END')

    @unittest.skipUnless(os.environ.get('PAPER_CHECK_LEAN_TESTS') == '1', 'native Lean audit is opt-in')
    def test_invalid_exception_schema(self):
        for exceptions in [{'typo': {}}, {'roots': []}, {'modules': {'X': None}}, []]:
            with self.assertRaises(ValueError):
                audit({}, set(), set(), set(), exceptions)


if __name__ == '__main__':
    unittest.main()
