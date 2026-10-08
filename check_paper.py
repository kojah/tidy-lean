#!/usr/bin/env python3
"""Keep the paper's formal results and the Lean proofs from drifting apart.

Every included formal result and paperclaim carries a label and a Lean link
or an explicit unmechanized reason. Definitions, contracts, obligations and
proposals also require evidence or an explicit classification. All statements,
including unmechanized ones, are fingerprinted. Include traversal rejects
omitted semantic files, missing inputs, duplicate includes and cycles.
Display math must inherit enclosing semantic evidence or carry a mathlink or
mathclass marker. Standalone displays are individually fingerprinted too.
Every authored project declaration must support a paper-linked declaration
transitively, or have an explicit exceptional retention reason. Unimported
project sources are errors. Retained exceptions remain visible as orphans.

Every included source also has a semantic-review receipt. Changes to prose
outside tracked environments require a new review; receipts are not proofs.
The checker cannot discover mathematical assertions in natural language.

A changed hash proves no equivalence and no difference: it marks the place
where a person has to compare the two again. After comparing, stamp the
label (--stamp LABEL ...), or record why they differ (--diverge LABEL
REASON). Only the labels named are stamped, so a stamp is a claim about
those labels alone.

Usage: check_paper.py [--stamp LABEL ...] [--diverge LABEL REASON]
Run from anywhere; needs `lake build` to have run in proofs/.
"""

import argparse, hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.environ.get('TIDYLEAN_PROJECT_ROOT', os.path.dirname(HERE)))
PROOFS = os.path.join(PROJECT_ROOT, 'proofs')
LOCK = os.path.join(PROOFS, 'check', 'paper-lock.json')
REVIEW = os.path.join(PROOFS, 'check', 'paper-review.json')
LAKE = os.environ.get('LAKE', os.path.expanduser('~/.elan/bin/lake'))
STANDARD_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}
LABEL_RE = r'(?:def|lem|prop|thm|cor|claim|con|obl|pdef):[A-Za-z0-9-]+'


def digest(text):
    return hashlib.sha256(' '.join(text.split()).encode()).hexdigest()[:16]


def paper_results():
    from paper_sources import collect
    root = Path(PROOFS).parent / 'paper'
    return collect([root / 'lockdoctor/deadlock.tex', root / 'heap-analysis/heap.tex'], digest)


def lean_facts(names, inventory=False):
    """Each Lean declaration's kind, location, axioms and statement."""
    if not names and not inventory:
        return {}
    dump = Path(HERE, 'Dump.lean').read_text().replace('import Lean\n', '')
    os.makedirs(os.path.join(PROOFS, '.lake'), exist_ok=True)
    # Concurrent checkers must not replace each other's Lean probe.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', dir=os.path.join(PROOFS, '.lake')) as probe:
        probe.write('import DeadlockProofs\n' + dump + '\n#paper_dump ' + ' '.join(sorted(names)) + '\n')
        if inventory:
            probe.write('#paper_inventory\n')
        probe.flush()
        run = subprocess.run([LAKE, 'env', 'lean', probe.name], cwd=PROOFS, capture_output=True, text=True)
    text = run.stdout + run.stderr
    facts = {}
    for m in re.finditer(r'@@MISSING (\S+)', text):
        facts[m.group(1)] = None
    for m in re.finditer(r'@@DECL (\S+)\n@@KIND (\S+)\n@@AT (\S+) (\S+)\n@@AXIOMS \[(.*?)\]\n@@TYPE\n(.*?)\n@@END', text, re.S):
        name, kind, module, lines, axioms, ty = m.groups()
        facts[name] = {'kind': kind, 'module': module, 'lines': lines,
                       'axioms': [a.strip() for a in axioms.split(',') if a.strip()], 'type': ty}
    if run.returncode != 0:
        sys.exit('lean failed:\n' + text[-2000:])
    if inventory:
        from paper_orphans import parse_inventory, source_inventory
        modules, nodes = parse_inventory(text)
        return facts, (modules, source_inventory(PROOFS, modules, nodes))
    return facts


def source(fact):
    """The declaration's source text, docstring included when it directly precedes."""
    path = os.path.join(PROOFS, *fact['module'].split('.')) + '.lean'
    lines = open(path).read().split('\n')
    a, b = (int(x) for x in fact['lines'].split('-'))
    start = a - 1
    # A docstring ends on the line before the declaration.
    if start > 0 and lines[start - 1].rstrip().endswith('-/'):
        while start > 0 and '/--' not in lines[start - 1]:
            start -= 1
        start -= 1
    return '\n'.join(lines[start:b])


def lean_fingerprint(fact):
    """A theorem is compared by its statement; a definition by its source,
    which is its statement."""
    return digest(fact['type'] if fact['kind'] == 'theorem' else source(fact))


def cited_labels():
    """Paper labels cited as '(paper LABEL)' in Lean docstrings, by label."""
    cited = {}
    for root, _, files in os.walk(os.path.join(PROOFS, 'DeadlockProofs')):
        for f in files:
            if f.endswith('.lean'):
                for m in re.finditer(r'\(paper (' + LABEL_RE + r')\)', open(os.path.join(root, f)).read()):
                    cited.setdefault(m.group(1), set()).add(os.path.relpath(os.path.join(root, f), PROOFS))
    return cited


def main():
    global PROJECT_ROOT, PROOFS, LOCK, REVIEW
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--project-root', type=Path, default=Path(PROJECT_ROOT),
                    help='repository to check (or set TIDYLEAN_PROJECT_ROOT)')
    ap.add_argument('--stamp', nargs='+', metavar='LABEL', help='record these labels as compared and matching')
    ap.add_argument('--diverge', nargs=2, metavar=('LABEL', 'REASON'), help='record that a label\'s paper and Lean statements differ')
    ap.add_argument('--review', nargs='+', metavar='PATH', help='record reviewed repository-relative source paths')
    ap.add_argument('--review-note', help='explain the semantic claim review; not a proof certificate')
    ap.add_argument('--math-report', action='store_true', help='list every display and its inherited or explicit evidence')
    ap.add_argument('--orphan-report', type=Path, help='write the complete Lean orphan/dependency audit as JSON')
    a = ap.parse_args()
    PROJECT_ROOT = str(a.project_root.resolve())
    PROOFS = os.path.join(PROJECT_ROOT, 'proofs')
    LOCK = os.path.join(PROOFS, 'check', 'paper-lock.json')
    REVIEW = os.path.join(PROOFS, 'check', 'paper-review.json')
    if a.review and not (a.review_note or '').strip():
        ap.error('--review requires --review-note')

    results, problems = paper_results()
    names = {n for r in results.values() for n in r['lean']}
    facts, (modules, nodes) = lean_facts(names, inventory=True)
    from paper_orphans import audit, source_modules
    standalone_path = Path(PROOFS, 'check', 'orphan-roots.json')
    standalone = json.loads(standalone_path.read_text()) if standalone_path.exists() else {}
    orphan_report = audit(nodes, modules, names, source_modules(PROOFS), standalone)
    problems.extend(orphan_report['errors'])
    if a.orphan_report:
        a.orphan_report.write_text(json.dumps(orphan_report, indent=2) + '\n')
    lock = json.load(open(LOCK)) if os.path.exists(LOCK) else {}

    current = {}
    for label, r in results.items():
        entry = {'tex': r['tex']}
        if r['classification']:
            entry['classification'] = r['classification']
        elif not r['lean']:
            entry['notlean'] = r['notlean']
        if r['lean']:
            entry['lean'] = {}
            for n in r['lean']:
                f = facts.get(n)
                if f is None:
                    problems.append(f"{r['where']}: {label}: Lean has no declaration {n}")
                    continue
                extra = set(f['axioms']) - STANDARD_AXIOMS
                if extra:
                    problems.append(f"{r['where']}: {label}: {n} depends on {', '.join(sorted(extra))}")
                entry['lean'][n] = lean_fingerprint(f)
        current[label] = entry

    for label, files in sorted(cited_labels().items()):
        if label not in results or not results[label]['lean']:
            problems.append(f"{', '.join(sorted(files))}: cites paper {label}, which the paper does not tag with \\lean")

    if a.stamp or a.diverge:
        for label in (a.stamp or []) + ([a.diverge[0]] if a.diverge else []):
            if label not in current:
                sys.exit(f'no paper result labelled {label}')
        if problems:
            sys.exit('Cannot stamp invalid evidence:\n' + '\n'.join(problems))
        for label in a.stamp or []:
            lock[label] = dict(current[label], status='matches')
        if a.diverge:
            lock[a.diverge[0]] = dict(current[a.diverge[0]], status='diverges: ' + a.diverge[1])
        with open(LOCK, 'w') as f:
            json.dump(dict(sorted(lock.items())), f, indent=1, ensure_ascii=False)
            f.write('\n')

    for label, entry in sorted(current.items()):
        where = results[label]['where']
        old = lock.get(label)
        if old is None:
            problems.append(f"{where}: {label}: never compared; compare and --stamp it")
        elif old.get('status', '').startswith('diverges'):
            problems.append(f"{where}: {label}: {old['status']}")
        elif {k: v for k, v in old.items() if k != 'status'} != entry:
            what = [k for k in ('tex', 'lean', 'notlean', 'classification') if old.get(k) != entry.get(k)]
            problems.append(f"{where}: {label}: {' and '.join(what)} changed since it was compared; compare and --stamp it")
    for label in sorted(set(lock) - set(current)):
        problems.append(f"paper-lock.json: {label} is no longer in the paper")

    from paper_sources import review_receipts, review_errors
    base = Path(PROOFS).parent
    current_reviews = review_receipts([base / 'paper/lockdoctor/deadlock.tex',
                                      base / 'paper/heap-analysis/heap.tex'], base, digest)
    recorded_reviews = json.load(open(REVIEW)) if os.path.exists(REVIEW) else {}
    if a.review:
        if problems:
            sys.exit('Cannot review invalid evidence:\n' + '\n'.join(problems))
        for path in a.review:
            if path not in current_reviews:
                sys.exit(f'not an included manuscript source: {path}')
            recorded_reviews[path] = dict(tex=current_reviews[path], reason=a.review_note)
        with open(REVIEW, 'w') as f:
            json.dump(dict(sorted(recorded_reviews.items())), f, indent=1)
            f.write('\n')
    problems.extend(review_errors(current_reviews, recorded_reviews))

    mechanized = sum(1 for r in results.values() if r['lean'])
    classified = sum(bool(r['classification']) for r in results.values())
    print(f"{len(results)} paper items: {mechanized} mechanized, "
          f"{len(results) - mechanized - classified} unmechanized, {classified} explicitly classified")
    print(f"Lean paper reachability: {len(orphan_report['orphaned_declarations'])} orphaned declarations "
          f"({len(orphan_report['orphaned_proofs'])} proofs), "
          f"{len(orphan_report['unimported_modules'])} unimported source modules; "
          f"{len(orphan_report['retained_orphans'])} explicitly retained orphans")
    displays = [r for r in results.values() if r['kind'] == 'display']
    print(f"Standalone display math: {len(displays)} tracked; "
          f"{sum(bool(r['lean']) for r in displays)} linked, "
          f"{sum(bool(r['notlean']) for r in displays)} explicitly unmechanized, "
          f"{sum(bool(r['classification']) for r in displays)} classified. "
          "Displays inside semantic blocks inherit their evidence.")
    if a.math_report:
        from paper_sources import math_coverage
        entries = [base / 'paper/lockdoctor/deadlock.tex', base / 'paper/heap-analysis/heap.tex']
        report = math_coverage(entries, results)
        print(f"All display math: {len(report)} blocks")
        for block in report:
            mode = 'inherited' if block['inherited'] else 'explicit'
            print(f"  {block['where']}: {block['evidence']} ({mode}: {block['label']})")
    for p in problems:
        print('  ' + p)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
