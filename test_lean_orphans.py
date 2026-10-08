"""Transport tests stay independent of an installed Lean toolchain."""
import json
import subprocess
import unittest
from unittest.mock import patch
from lean_orphans import audit


class LeanAuditTransportTests(unittest.TestCase):
    def response(self, text, status=0):
        return subprocess.CompletedProcess([], status, text, '')

    @patch('lean_orphans.subprocess.run')
    def test_serializes_roots_and_enriched_edges_without_running_python_graph_logic(self, run):
        def inspect(command, **kwargs):
            from pathlib import Path
            payload = json.loads(Path(command[-1]).read_text())
            self.assertEqual(payload['paper_roots'], ['paper'])
            self.assertEqual(payload['nodes'][0]['source_dependencies'], ['erased'])
            self.assertEqual(kwargs['cwd'], '/workspace/proofs')
            self.assertIn('Orphans.lean', command[-2])
            return self.response('@@ORPHAN_AUDIT {"report":{"paper_connected":["paper","erased"]}}\n')
        run.side_effect = inspect
        report = audit({'paper': {'name': 'paper', 'source_dependencies': ['erased']}},
                       set(), {'paper'}, set(), proofs='/workspace/proofs', lake='lake')
        self.assertEqual(report['paper_connected'], ['paper', 'erased'])

    @patch('lean_orphans.subprocess.run')
    def test_native_schema_errors_are_not_successful_audits(self, run):
        run.return_value = self.response('@@ORPHAN_AUDIT {"error":"invalid exception"}\n', 1)
        with self.assertRaisesRegex(ValueError, 'invalid exception'):
            audit({}, set(), set(), set(), proofs='/workspace/proofs')

    @patch('lean_orphans.subprocess.run')
    def test_failed_or_ambiguous_process_output_has_no_fallback(self, run):
        for text, status in [('compiler failed', 1),
                             ('@@ORPHAN_AUDIT {"report":{}}\n', 1),
                             ('@@ORPHAN_AUDIT {"report":{}}\n' * 2, 0)]:
            with self.subTest(text=text, status=status):
                run.return_value = self.response(text, status)
                with self.assertRaises(RuntimeError):
                    audit({}, set(), set(), set(), proofs='/workspace/proofs')


if __name__ == '__main__':
    unittest.main()
