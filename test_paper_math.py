import tempfile
import unittest
from pathlib import Path

from check_paper import digest
from paper_sources import collect


class MathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'sections').mkdir()
        self.entry = self.root / 'paper.tex'
        self.entry.write_text(r'\input{sections/a}')

    def scan(self, source):
        (self.root / 'sections/a.tex').write_text(source)
        return collect([self.entry], digest)

    def owner(self, tag=r'\lean{Proof.good}'):
        return r'\begin{theorem}\label{thm:x}' + tag + r'X\end{theorem}'

    def test_standalone_display_forms_fail_without_evidence(self):
        forms = [r'\[x\]', '$$x$$']
        for env in ('equation', 'equation*', 'align', 'align*', 'alignat',
                    'gather*', 'multline', 'displaymath', 'eqnarray*', 'flalign'):
            forms.append(r'\begin{' + env + '}x' + r'\end{' + env + '}')
        for form in forms:
            with self.subTest(form=form):
                _, errors = self.scan(form)
                self.assertTrue(any('unlinked display' in e for e in errors), errors)

    def test_math_inherits_mechanized_or_explicit_unmechanized_owner(self):
        for tag in (r'\lean{Proof.good}', r'\notlean{remaining proof}'):
            items, errors = self.scan(self.owner(tag).replace('X', r'\[x\]'))
            self.assertEqual(errors, [])
            self.assertEqual(set(items), {'thm:x'})

    def test_inheritance_does_not_hide_invalid_owner(self):
        _, errors = self.scan(self.owner('').replace('X', r'\[x\]'))
        self.assertTrue(any('evidence tag' in e for e in errors))

    def test_link_to_later_result_and_multiple_targets(self):
        source = r'\mathlink{math:x}{thm:x,thm:y}\[x\]' + self.owner()
        source += self.owner(r'\lean{Proof.other}').replace('thm:x', 'thm:y')
        items, errors = self.scan(source)
        self.assertEqual(errors, [])
        self.assertEqual(items['math:x']['lean'], ['Proof.good', 'Proof.other'])

    def test_broken_unproved_and_circular_links_fail(self):
        for target, owner in [('missing', ''), ('thm:x', self.owner(r'\notlean{open}')),
                              ('math:x', '')]:
            _, errors = self.scan(r'\mathlink{math:x}{' + target + r'}\[x\]' + owner)
            self.assertTrue(any('not a Lean-backed' in e for e in errors), errors)

    def test_classifications_and_balanced_reasons(self):
        for kind in ('definition', 'illustrative', 'obligation', 'unmechanized'):
            source = r'\mathclass{math:x}{' + kind + r'}{Review \code{nested {terms}}.}\[x\]'
            items, errors = self.scan(source)
            self.assertEqual(errors, [])
            item = items['math:x']
            self.assertEqual(item['lean'], [])
            if kind == 'unmechanized':
                self.assertIsNotNone(item['notlean'])
            else:
                self.assertEqual(item['classification']['kind'], kind)

    def test_invalid_classification_empty_reason_and_id_fail(self):
        for marker in [r'\mathclass{math:x}{proved}{because}',
                       r'\mathclass{math:x}{definition}{}',
                       r'\mathclass{x}{definition}{because}',
                       r'\mathclass{math:x}{definition}{unclosed']:
            _, errors = self.scan(marker + r'\[x\]')
            self.assertTrue(errors)

    def test_duplicate_and_orphan_markers_fail(self):
        marker = r'\mathclass{math:x}{definition}{notation}'
        for source, message in [(marker, 'orphan'), (marker + 'prose' + r'\[x\]', 'orphan'),
                                (marker + marker + r'\[x\]', 'orphan'),
                                ((marker + r'\[x\]') * 2, 'duplicate')]:
            _, errors = self.scan(source)
            self.assertTrue(any(message in e for e in errors), errors)

    def test_equation_and_evidence_changes_are_fingerprinted(self):
        source = r'\mathclass{math:x}{obligation}{coverage}\[x=y\]'
        first, _ = self.scan(source)
        for altered in [source.replace('x=y', 'x=z'), source.replace('coverage', 'binding')]:
            second, errors = self.scan(altered)
            self.assertEqual(errors, [])
            self.assertNotEqual(first['math:x']['tex'], second['math:x']['tex'])

    def test_link_target_changes_are_fingerprinted(self):
        source = r'\mathlink{math:x}{thm:x}\[x\]' + self.owner()
        source += self.owner().replace('thm:x', 'thm:y')
        first, _ = self.scan(source)
        second, errors = self.scan(source.replace('{math:x}{thm:x}', '{math:x}{thm:y}'))
        self.assertEqual(errors, [])
        self.assertNotEqual(first['math:x']['tex'], second['math:x']['tex'])

    def test_literals_comments_inline_math_and_row_spacing_are_ignored(self):
        source = '% \\[hidden\\]\n' + r'$x$ \(y\) \\[2pt] \verb|$$literal$$|'
        for env in ('Verbatim', 'verbatim', 'lstlisting', 'minted'):
            source += r'\begin{' + env + r'}\[x\] $$y$$ \mathlink{math:x}{bad}\end{' + env + '}'
        self.assertEqual(self.scan(source), ({}, []))

    def test_literal_semantic_examples_still_affect_formal_fingerprint(self):
        source = self.owner().replace('X', r'\begin{Verbatim}code one\end{Verbatim}')
        first, _ = self.scan(source)
        second, _ = self.scan(source.replace('code one', 'code two'))
        self.assertNotEqual(first['thm:x']['tex'], second['thm:x']['tex'])

    def test_alignment_children_belong_to_one_display(self):
        source = r'\mathclass{math:x}{definition}{notation}\[\begin{aligned}x&=y\\z&=w\end{aligned}\]'
        items, errors = self.scan(source)
        self.assertEqual(errors, [])
        self.assertEqual(set(items), {'math:x'})

    def test_broken_nested_and_crossing_displays_fail(self):
        for source in [r'\[x', r'\]x', r'\begin{align}x\end{equation}',
                       r'\[\begin{equation}x\end{equation}\]',
                       r'\[' + self.owner() + r'\]']:
            _, errors = self.scan(source)
            self.assertTrue(errors)

    def test_inherited_equation_cannot_override_evidence(self):
        source = self.owner().replace('X', r'\mathclass{math:x}{illustrative}{skip}\[x\]')
        _, errors = self.scan(source)
        self.assertTrue(any('override' in e for e in errors), errors)

    def test_omitted_math_only_file_is_detected(self):
        self.scan(r'\[x\]')
        self.entry.write_text('')
        _, errors = collect([self.entry], digest)
        self.assertTrue(any('omitted' in e for e in errors))

    def test_included_equation_and_cross_file_link(self):
        (self.root / 'sections/b.tex').write_text(self.owner())
        items, errors = self.scan(r'\mathlink{math:x}{thm:x}\[x\]\input{sections/b}')
        self.assertEqual(errors, [])
        self.assertEqual(items['math:x']['lean'], ['Proof.good'])

    def test_report_distinguishes_inherited_unproved_and_unlinked_math(self):
        from paper_sources import math_coverage
        source = self.owner(r'\notlean{open}').replace('X', r'\[x\]')
        source += '\n' + r'\mathclass{math:x}{definition}{notation}\[y\]' + '\n' + r'\[z\]'
        items, _ = self.scan(source)
        report = math_coverage([self.entry], items)
        self.assertEqual([row['evidence'] for row in report], ['unmechanized', 'definition', 'unlinked'])
        self.assertEqual([row['inherited'] for row in report], [True, False, False])

    def test_macro_declarations_are_not_orphan_markers(self):
        source = r'\newcommand{\mathlink}[2]{}\newcommand{\mathclass}[3]{}'
        self.assertEqual(self.scan(source), ({}, []))

    def test_same_line_displays_have_distinct_report_locations(self):
        from paper_sources import math_coverage
        source = r'\mathclass{math:x}{definition}{notation}\[x\]'
        source += r'\mathclass{math:y}{unmechanized}{open}\[y\]'
        items, errors = self.scan(source)
        self.assertEqual(errors, [])
        report = math_coverage([self.entry], items)
        self.assertEqual([row['label'] for row in report], ['math:x', 'math:y'])
        self.assertNotEqual(report[0]['where'], report[1]['where'])


if __name__ == '__main__':
    unittest.main()
