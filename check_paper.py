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


def manuscript_fingerprint():
    """Every manuscript source and the checker's own code: what the paper
    side of a run depends on."""
    root = Path(PROOFS).parent / 'paper'
    parts = []
    for path in sorted(root.rglob('*.tex')):
        parts.append(str(path.relative_to(root)) + '\0' + path.read_text())
    for path in sorted(Path(HERE).glob('*.py')):
        parts.append(path.read_text())
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def cached_json(name, key, compute):
    """A JSON-serializable result under proofs/.lake/paper-check/NAME, by key."""
    cache_dir = Path(PROOFS, '.lake', 'paper-check', name)
    cached = cache_dir / (key + '.json')
    if cached.is_file():
        return json.loads(cached.read_text())
    value = compute()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for stale in cache_dir.glob('*.json'):
            stale.unlink()
        cached.write_text(json.dumps(value))
    except OSError:
        pass  # no proof workspace to cache in, as in the tests
    return value


def paper_results():
    from paper_sources import collect
    root = Path(PROOFS).parent / 'paper'
    return cached_json('results', manuscript_fingerprint(),
                       lambda: collect([root / 'lockdoc/deadlock.tex', root / 'heap-analysis/heap.tex'], digest))


def proofs_fingerprint():
    """The compiled proofs the Lean probe reads: every olean's path, size
    and modification time, and the dependency manifest."""
    root = Path(PROOFS, '.lake', 'build', 'lib', 'lean')
    manifest = Path(PROOFS, 'lake-manifest.json')
    parts = [manifest.read_text() if manifest.is_file() else '']
    compiled = sorted(list(root.rglob('*.olean')) + list(root.rglob('*.ilean'))) if root.is_dir() else []
    for path in compiled:
        st = path.stat()
        parts.append(f'{path.relative_to(root)} {st.st_size} {st.st_mtime_ns}')
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def lean_probe(source):
    """Run a Lean probe over the compiled proofs and return its output. The
    output depends only on the probe and the compiled proofs, so it is
    cached by both: a run after a change to the manuscript alone reads the
    cache instead of dumping every declaration again."""
    cache_dir = Path(PROOFS, '.lake', 'paper-check')
    key = hashlib.sha256((proofs_fingerprint() + '\0' + source).encode()).hexdigest()
    cached = cache_dir / (key + '.txt')
    if cached.is_file():
        return cached.read_text(), 0
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_dir = None  # no proof workspace to cache in, as in the tests
    # Concurrent checkers must not replace each other's Lean probe.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', dir=os.path.join(PROOFS, '.lake')) as probe:
        probe.write(source)
        probe.flush()
        run = subprocess.run([LAKE, 'env', 'lean', probe.name], cwd=PROOFS, capture_output=True, text=True)
    text = run.stdout + run.stderr
    if run.returncode == 0 and cache_dir is not None:
        for stale in cache_dir.glob('*.txt'):
            stale.unlink()
        cached.write_text(text)
    return text, run.returncode


def probe_source(names, inventory):
    """The probe dumping names and, with inventory, the inventory of every
    project module (True) or of the modules listed."""
    dump = Path(HERE, 'Dump.lean').read_text().replace('import Lean\n', '')
    entry = 'Proofs' if Path(PROOFS, 'Proofs.lean').is_file() else 'DeadlockProofs'
    source = f'import {entry}\n' + dump + '\n'
    if names:
        source += '#paper_dump ' + ' '.join(sorted(names)) + '\n'
    if inventory is True:
        source += '#paper_inventory\n'
    elif inventory:
        source += '#paper_inventory ' + ' '.join(sorted(inventory)) + '\n'
    return source


def module_graph():
    """The project's modules, each with the project modules it imports."""
    from paper_orphans import PROJECT_LIBRARIES
    root = Path(PROOFS)
    graph = {}
    for library in PROJECT_LIBRARIES:
        paths = list(Path(root, library).rglob('*.lean')) + [Path(root, library + '.lean')]
        for path in paths:
            if not path.is_file():
                continue
            module = '.'.join(path.relative_to(root).with_suffix('').parts)
            graph[module] = re.findall(r'^import ((?:' + '|'.join(PROJECT_LIBRARIES) + r')\S*)',
                                       path.read_text(), re.M)
    return graph


def module_stamp(module):
    """The compiled module: its olean and ilean's size and modification time."""
    parts = []
    for suffix in ('.olean', '.ilean'):
        path = Path(PROOFS, '.lake', 'build', 'lib', 'lean', *module.split('.')).with_suffix(suffix)
        st = path.stat() if path.is_file() else None
        parts.append(f'{st.st_size} {st.st_mtime_ns}' if st else 'missing')
    return ' '.join(parts)


def closure_stamps(graph):
    """Per module, a digest of its stamp and its imports' closure: what a
    declaration's facts, its axioms included, depend on."""
    own = {module: module_stamp(module) for module in graph}
    manifest = Path(PROOFS, 'lake-manifest.json')
    salt = manifest.read_text() if manifest.is_file() else ''
    closure = {}

    def visit(module, trail=()):
        if module in closure:
            return closure[module]
        if module in trail or module not in graph:
            return ''
        parts = [own[module]] + sorted(visit(imported, trail + (module,)) for imported in graph[module])
        closure[module] = hashlib.sha256((salt + '\n'.join(parts)).encode()).hexdigest()
        return closure[module]

    for module in graph:
        visit(module)
    return own, closure


def facts_and_inventory(names):
    """The facts of the cited names and the project's declaration inventory,
    from per-module caches under proofs/.lake/paper-check/modules, with one
    Lean probe for the modules whose compiled form changed and the names not
    yet placed in a module. A module's inventory depends on its own olean;
    its declarations' facts on its imports' closure as well."""
    from paper_orphans import parse_inventory, source_inventory
    graph = module_graph()
    own, closure = closure_stamps(graph)
    base = Path(PROOFS, '.lake', 'paper-check', 'modules')
    placed = cached_read(base / 'names.json') or {}
    facts, nodes = {}, {}
    stale_modules, missing_names = set(), set()
    for module in graph:
        entry = cached_read(base / 'inventory' / (module + '.json'))
        if entry and entry.get('key') == hashlib.sha256(own[module].encode()).hexdigest():
            nodes.update(entry['nodes'])
        else:
            stale_modules.add(module)
    for name in names:
        module = placed.get(name)
        entry = cached_read(base / 'facts' / (module + '.json')) if module else None
        if entry and entry.get('key') == closure.get(module) and name in entry['facts']:
            facts[name] = entry['facts'][name]
        else:
            missing_names.add(name)
    if stale_modules or missing_names:
        fresh = lean_facts(missing_names, inventory=stale_modules or None)
        fresh_facts, (_, fresh_nodes) = fresh if stale_modules else (fresh, (None, {}))
        facts.update(fresh_facts)
        nodes.update(fresh_nodes)
        by_module = {}
        for name, fact in fresh_facts.items():
            if fact is not None:
                placed[name] = fact['module']
                by_module.setdefault(fact['module'], {})[name] = fact
        for module, fresh_of in by_module.items():
            entry = cached_read(base / 'facts' / (module + '.json')) or {}
            kept = entry.get('facts', {}) if entry.get('key') == closure.get(module) else {}
            cached_write(base / 'facts' / (module + '.json'), {'key': closure.get(module), 'facts': {**kept, **fresh_of}})
        for module in stale_modules:
            cached_write(base / 'inventory' / (module + '.json'),
                         {'key': hashlib.sha256(own[module].encode()).hexdigest(),
                          'nodes': {n: node for n, node in fresh_nodes.items() if node['module'] == module}})
        cached_write(base / 'names.json', placed)
    modules = {module for module in graph if own[module] != 'missing missing'}
    return facts, (modules, source_inventory(PROOFS, modules, nodes))


def cached_read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def cached_write(path, value):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(value))
    except OSError:
        pass  # no proof workspace to cache in, as in the tests


def lean_facts(names, inventory=False):
    """Each Lean declaration's kind, location, axioms and statement."""
    if not names and not inventory:
        return {}
    os.makedirs(os.path.join(PROOFS, '.lake'), exist_ok=True)
    text, returncode = lean_probe(probe_source(names, inventory))
    facts = {}
    for m in re.finditer(r'@@MISSING (\S+)', text):
        facts[m.group(1)] = None
    for m in re.finditer(r'@@DECL (\S+)\n@@KIND (\S+)\n@@AT (\S+) (\S+)\n@@AXIOMS \[(.*?)\]\n@@TYPE\n(.*?)\n@@END', text, re.S):
        name, kind, module, lines, axioms, ty = m.groups()
        facts[name] = {'kind': kind, 'module': module, 'lines': lines,
                       'axioms': [a.strip() for a in axioms.split(',') if a.strip()], 'type': ty}
    if returncode != 0:
        sys.exit('lean failed:\n' + text[-2000:])
    if inventory:
        from paper_orphans import parse_inventory
        return facts, parse_inventory(text)  # raw nodes; facts_and_inventory adds the source references
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
    from paper_orphans import PROJECT_LIBRARIES
    for root, _, files in (entry for library in PROJECT_LIBRARIES for entry in os.walk(os.path.join(PROOFS, library))):
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

    import paper_latex
    paper_latex.CACHE_DIR = os.path.join(PROOFS, '.lake', 'paper-check', 'latex')
    results, problems = paper_results()
    names = {n for r in results.values() for n in r['lean']}
    from paper_orphans import audit, source_modules
    standalone_path = Path(PROOFS, 'check', 'orphan-roots.json')
    standalone = json.loads(standalone_path.read_text()) if standalone_path.exists() else {}
    # The facts and the orphan report are functions of the compiled proofs,
    # the cited names and the audit's inputs: a run that changes none of
    # them reads both back without opening the probe's output.
    facts_key = hashlib.sha256((proofs_fingerprint() + '\0' + probe_source(names, True)).encode()).hexdigest()
    sources = source_modules(PROOFS)
    orphan_key = hashlib.sha256((facts_key + Path(HERE, 'Orphans.lean').read_text() + json.dumps(
        [sorted(names), sorted(sources), standalone], sort_keys=True)).encode()).hexdigest()
    probed = []

    def probe():
        if not probed:
            probed.append(facts_and_inventory(names))
        return probed[0]

    facts = cached_json('facts', facts_key, lambda: probe()[0])
    orphan_report = cached_json('orphans', orphan_key,
                                lambda: audit(probe()[1][1], probe()[1][0], names, sources, standalone,
                                              proofs=PROOFS, lake=LAKE))
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
    current_reviews = cached_json('reviews', manuscript_fingerprint(), lambda: review_receipts(
        [base / 'paper/lockdoc/deadlock.tex', base / 'paper/heap-analysis/heap.tex'], base, digest))
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
        entries = [base / 'paper/lockdoc/deadlock.tex', base / 'paper/heap-analysis/heap.tex']
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
