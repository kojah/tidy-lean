"""Parser-specific regressions: nesting and token boundaries, not just happy paths."""
import tempfile
import unittest
from pathlib import Path

from check_paper import digest
from paper_sources import collect


class LatexParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.entry = Path(self.tmp.name) / 'paper.tex'

    def scan(self, text):
        self.entry.write_text(text)
        return collect([self.entry], digest)

    def test_nested_unmechanized_reason_is_complete(self):
        template = r'\begin{theorem}[Title]\label{thm:x}\notlean{REASON}Statement.\end{theorem}'
        reason = r'Runtime \code{testing/synctest} semantics, outside the model'
        items, errors = self.scan(template.replace('REASON', reason))
        self.assertEqual(errors, [])
        self.assertEqual(items['thm:x']['notlean'], reason)
        other, errors = self.scan(template.replace('REASON', 'Different premise'))
        self.assertEqual(errors, [])
        self.assertEqual(items['thm:x']['tex'], other['thm:x']['tex'])

    def test_nested_status_reason_and_optional_title(self):
        source = r'\begin {obligation}[A title with {groups}]\label{x}'
        source += r'\paperstatus{obligation}{Native \code{bind} coverage}\[x\]\end {obligation}'
        items, errors = self.scan(source)
        self.assertEqual(errors, [])
        self.assertEqual(items['x']['classification']['reason'], r'Native \code{bind} coverage')
        changed, _ = self.scan(source.replace('A title', 'Another title'))
        self.assertNotEqual(items['x']['tex'], changed['x']['tex'])

    def test_declaration_bodies_do_not_introduce_claims_or_includes(self):
        source = r'\newcommand{\fake}{\begin{theorem}\label{x}\lean{Fake}\[x\]\end{theorem}\input{missing}}'
        self.assertEqual(self.scan(source), ({}, []))

    def test_literal_input_does_not_load_file(self):
        self.assertEqual(self.scan(r'\verb|\input{missing}|'), ({}, []))

    def test_comment_between_marker_arguments(self):
        source = '\\mathclass% comment\n{math:x}% comment\n{definition}{Notation}\n\\[x\\]'
        items, errors = self.scan(source)
        self.assertEqual(errors, [])
        self.assertIn('math:x', items)

    def test_comments_and_escaped_percent_in_fingerprint(self):
        source = '\\begin{theorem}\\label{x}\\lean{A}\\% literal\n% ignored\nStatement\\end{theorem}'
        first, errors = self.scan(source)
        self.assertEqual(errors, [])
        second, _ = self.scan(source.replace('ignored', 'different comment'))
        self.assertEqual(first['x']['tex'], second['x']['tex'])
        third, _ = self.scan(source.replace('literal', 'changed literal'))
        self.assertNotEqual(first['x']['tex'], third['x']['tex'])

    def test_display_inside_macro_argument_is_checked(self):
        _, errors = self.scan(r'\textbf{\[x\]}')
        self.assertTrue(any('unlinked display' in error for error in errors), errors)

    def test_nonsemantic_malformed_structure_fails_closed(self):
        for source in [r'\begin{itemize}text\end{enumerate}', r'{unclosed',
                       r'\begin{Verbatim}\[literal', r'\verb|unclosed', '$unclosed']:
            with self.subTest(source=source):
                _, errors = self.scan(source)
                self.assertTrue(any('parse error' in error for error in errors), errors)

    def test_cross_file_environment_is_rejected(self):
        (self.entry.parent / 'part.tex').write_text(r'\end{theorem}')
        _, errors = self.scan(r'\begin{theorem}\input{part}')
        self.assertTrue(any('parse error' in error for error in errors), errors)

    def test_starred_verb_is_literal(self):
        self.assertEqual(self.scan(r'\verb*|\[x\] \mathlink{math:x}{bad}|'), ({}, []))

    def test_marker_reason_cannot_supply_another_evidence_tag(self):
        source = r'\begin{theorem}\label{x}\notlean{Reason \lean{Fake}}text\end{theorem}'
        _, errors = self.scan(source)
        self.assertTrue(any('evidence tag' in error for error in errors), errors)

    def test_raw_tex_definition_is_not_silently_accepted(self):
        _, errors = self.scan(r'\def\fake{\[x\]}')
        self.assertTrue(any('raw TeX definitions' in error for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
