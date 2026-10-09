import tempfile
import unittest
from pathlib import Path

from paper_sources import collect
from check_paper import digest


class FormulaCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.entry = self.root / 'paper.tex'
        (self.root / 'sections').mkdir()
        self.command = r'\leanformula[label={def:x},title={Example},names={x=y}]{A.theorem}'

    def collect(self, source):
        self.entry.write_text(source)
        return collect([self.entry], digest)

    def test_native_declaration_is_evidence_and_settings_are_fingerprinted(self):
        items, errors = self.collect(self.command)
        self.assertEqual(errors, [])
        self.assertEqual(items['def:x']['lean'], ['A.theorem'])
        changed, errors = self.collect(self.command.replace('x=y', 'x=z'))
        self.assertEqual(errors, [])
        self.assertNotEqual(items['def:x']['tex'], changed['def:x']['tex'])

    def test_invalid_or_duplicate_commands_fail(self):
        for source in [self.command * 2, self.command.replace('x=y', 'x=y x=z'),
                       self.command.replace('title={Example}', 'body={x=y}'),
                       self.command.replace('A.theorem', r'\evil')]:
            with self.subTest(source=source):
                _, errors = self.collect(source)
                self.assertTrue(errors)

    def test_omitted_command_and_template(self):
        (self.root / 'sections/omitted.tex').write_text(self.command)
        _, errors = self.collect('')
        self.assertTrue(any('omitted' in error for error in errors), errors)
        (self.root / 'sections/omitted.tex').unlink()
        items, errors = self.collect(r'\newcommand{\example}{' + self.command + '}')
        self.assertEqual((items, errors), ({}, []))

    def test_display_expression_links_to_command(self):
        items, errors = self.collect(self.command + r'\mathlink{math:x}{def:x}' +
                                     r'\paperexpr[layout=display]{expression}')
        self.assertEqual(errors, [])
        self.assertEqual(items['math:x']['lean'], ['A.theorem'])
        _, errors = self.collect(r'\paperexpr[layout=display]{expression}')
        self.assertTrue(any('unlinked display' in error for error in errors), errors)

    def test_literal_lean_source_does_not_create_tex_items(self):
        source = (r'\begin{leancontext}{(x : Nat)}'
                  r'\leanexpr|"\begin{theorem}$x$ % fake"|\end{leancontext}')
        items, errors = self.collect(source)
        self.assertEqual((items, errors), ({}, []))
        source = (r'\begin{leancontext}{(x : Nat)}'
                  r'\mathclass{math:direct}{definition}{Typed expression}'
                  r'\leanexpr[layout=display]{{n : Nat | n % 2 = 0}}\end{leancontext}')
        items, errors = self.collect(source)
        self.assertEqual(errors, [])
        self.assertEqual(items['math:direct']['classification']['kind'], 'definition')
        _, errors = self.collect(source.replace(r'\mathclass{math:direct}{definition}{Typed expression}', ''))
        self.assertTrue(any('unlinked display' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
