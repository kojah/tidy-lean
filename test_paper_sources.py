import tempfile
import unittest
from pathlib import Path
from paper_sources import collect
from check_paper import digest


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'sections').mkdir()
        self.entry = self.root / 'paper.tex'
        self.entry.write_text(r'\input{sections/a}')

    def run_source(self, source):
        (self.root / 'sections/a.tex').write_text(source)
        return collect([self.entry], digest)

    def test_untagged_definition_and_obligation_fail(self):
        for kind in ('definition', 'obligation', 'paperclaim'):
            with self.subTest(kind=kind):
                _, errors = self.run_source(r'\begin{' + kind + r'}\label{x}text\end{' + kind + '}')
                self.assertTrue(any('evidence tag' in e for e in errors))

    def test_proof_claim_cannot_be_classified_as_obligation(self):
        _, errors = self.run_source(r'\begin{paperclaim}\label{x}\paperstatus{obligation}{later}text\end{paperclaim}')
        self.assertTrue(any('invalid status' in e for e in errors))

    def test_classification_and_unproved_text_are_fingerprinted(self):
        for env, tag in [('obligation', r'\paperstatus{obligation}{adapter premise}'),
                         ('paperclaim', r'\notlean{open proof}')]:
            template = r'\begin{' + env + r'}\label{x}' + tag + '{}' + r'\end{' + env + '}'
            a, errors = self.run_source(template.replace('{}', 'old'))
            self.assertEqual(errors, [])
            b, errors = self.run_source(template.replace('{}', 'new'))
            self.assertNotEqual(a['x']['tex'], b['x']['tex'])

    def test_commented_claim_not_tracked(self):
        items, errors = self.run_source('% \\begin{theorem}fake\\end{theorem}\n')
        self.assertEqual((items, errors), ({}, []))

    def test_omitted_file_is_error(self):
        self.run_source(r'\begin{theorem}\label{x}\lean{A}text\end{theorem}')
        self.entry.write_text('')
        _, errors = collect([self.entry], digest)
        self.assertTrue(any('omitted' in e for e in errors))

    def test_missing_cycle_and_repeat(self):
        for source, message in [(r'\input{absent}', 'missing'),
                                (r'\input{paper}', 'cyclic'),
                                (r'\input{sections/a}', 'repeated')]:
            if message == 'repeated':
                self.entry.write_text(r'\input{sections/a}\input{sections/a}')
                source = ''
            _, errors = self.run_source(source)
            self.assertTrue(any(message in e for e in errors), errors)

    def test_duplicate_labels_and_multiple_tags(self):
        claim = r'\begin{paperclaim}\label{x}\lean{A}text\end{paperclaim}'
        _, errors = self.run_source(claim + claim)
        self.assertTrue(any('duplicate' in e for e in errors))
        _, errors = self.run_source(claim.replace(r'\lean{A}', r'\lean{A}\notlean{reason}'))
        self.assertTrue(any('evidence tag' in e for e in errors))

    def test_nested_include_is_checked(self):
        (self.root / 'sections/b.tex').write_text(r'\begin{theorem}\label{x}\lean{A}text\end{theorem}')
        items, errors = self.run_source(r'\input{sections/b}')
        self.assertEqual(errors, [])
        self.assertEqual(items['x']['lean'], ['A'])
    def test_broken_or_nested_semantic_environment_fails(self):
        for source in [r'\begin{paperclaim}', r'\end{obligation}',
                       r'\begin{paperclaim}\begin{theorem}\end{theorem}\end{paperclaim}']:
            _, errors = self.run_source(source)
            self.assertTrue(any('environment' in e for e in errors), errors)

    def test_verbatim_commands_are_not_claims(self):
        items, errors = self.run_source(r'\begin{Verbatim}\begin{theorem}\end{Verbatim}')
        self.assertEqual((items, errors), ({}, []))

    def test_empty_or_wrong_classification_fails(self):
        for tag in [r'\paperstatus{definition}{}', r'\paperstatus{proved}{trust me}']:
            _, errors = self.run_source(r'\begin{definition}\label{x}' + tag + r'text\end{definition}')
            self.assertTrue(any('status' in e for e in errors))


class ReviewTests(unittest.TestCase):
    def test_unmarked_prose_changes_require_review(self):
        from paper_sources import review_errors
        recorded = {'a.tex': {'tex': digest('An old explanation.'), 'reason': 'reviewed'}}
        self.assertEqual(review_errors({'a.tex': digest('An old explanation.')}, recorded), [])
        self.assertTrue(review_errors({'a.tex': digest('A new mathematical claim.')}, recorded))

    def test_removing_reviewed_source_is_not_silent(self):
        from paper_sources import review_errors
        self.assertTrue(review_errors({}, {'gone.tex': {'tex': 'old', 'reason': 'reviewed'}}))


class ProbeTests(unittest.TestCase):
    def test_failed_probe_rejects_partial_success(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from check_paper import lean_facts
        partial = '@@DECL A\n@@KIND theorem\n@@AT Module 1-2\n@@AXIOMS []\n@@TYPE\nTrue\n@@END'
        with tempfile.TemporaryDirectory() as tmp:
            with patch('check_paper.PROOFS', tmp), patch('check_paper.subprocess.run',
                    return_value=SimpleNamespace(returncode=1, stdout=partial, stderr='probe error')):
                with self.assertRaises(SystemExit):
                    lean_facts({'A'})


if __name__ == '__main__':
    unittest.main()
