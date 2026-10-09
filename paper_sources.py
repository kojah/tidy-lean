"""Traverse parsed manuscripts and account for their semantic evidence."""
from pathlib import Path

from paper_latex import parse, is_semantic, is_display
from paper_math import collect_math, coverage_report
from paper_formula_commands import collect_formulas

STATUS_KINDS = {'definition': 'definition', 'contract': 'obligation',
                'obligation': 'obligation', 'proposal': 'proposal'}


def included_sources(entry):
    """Follow literal include macros from the syntax tree; fail on broken input."""
    entry = Path(entry).resolve()
    root, sources, problems, seen = entry.parent, [], [], set()

    def visit(path, stack):
        if path in stack:
            problems.append(f'{path}: cyclic manuscript include')
            return
        if path in seen:
            problems.append(f'{path}: repeated manuscript include')
            return
        seen.add(path)
        if not path.is_file():
            problems.append(f'{path}: missing manuscript include')
            return
        doc = parse(path.read_text(), path)
        sources.append(doc)
        problems.extend(doc.errors)
        for node in doc.all_nodes():
            if getattr(node, 'macroname', None) not in ('input', 'include'):
                continue
            try:
                name, = doc.args(node)
                if not name or any(c in name for c in ('\\', '{', '}')):
                    raise ValueError(f'{doc.where(node)}: include path must be literal')
                target = root / name
                if not target.suffix:
                    target = target.with_suffix('.tex')
                visit(target.resolve(), stack + [path])
            except ValueError as error:
                problems.append(str(error))

    visit(entry, [])
    for path in (root / 'sections').rglob('*.tex'):
        if path.resolve() in seen:
            continue
        doc = parse(path.read_text(), path.resolve())
        problems.extend(doc.errors)
        if any(is_semantic(n) or is_display(n) or getattr(n, 'macroname', None) == 'leanformula'
               for n in doc.all_nodes()):
            problems.append(f'{path}: semantic items in a file omitted from manuscript')
    return sources, problems


def collect(entries, digest):
    out, problems, all_sources = {}, [], []
    for entry in entries:
        sources, errors = included_sources(entry)
        all_sources.extend(sources)
        problems.extend(errors)
        for doc in sources:
            problems.extend(collect_formulas(doc, out, digest))
            for node in filter(is_semantic, doc.all_nodes()):
                kind, where = node.environmentname, doc.where(node)
                try:
                    labels = doc.macros('label', node.nodelist)
                    if len(labels) != 1:
                        problems.append(f'{where}: {kind} needs exactly one label')
                        continue
                    label, = doc.args(labels[0])
                    if not label:
                        problems.append(f'{where}: empty result label')
                        continue
                    if label in out:
                        problems.append(f'{where}: duplicate result label {label}')
                        continue
                    tags = [n for name in ('lean', 'notlean', 'paperstatus')
                            for n in doc.macros(name, node.nodelist)]
                    if len(tags) != 1:
                        problems.append(f'{where}: {label} needs exactly one evidence tag')
                        continue
                    tag, = tags
                    args = doc.args(tag)
                    lean, absent, classification = [], None, None
                    if tag.macroname == 'paperstatus':
                        status, reason = args
                        if status != STATUS_KINDS.get(kind) or not reason:
                            problems.append(f'{where}: invalid status for {kind}')
                            continue
                        classification = dict(kind=status, reason=reason)
                    elif not args[0]:
                        problems.append(f'{where}: empty evidence tag')
                        continue
                    elif tag.macroname == 'lean':
                        lean = [name.strip() for name in args[0].split(',')]
                        if any(not name for name in lean):
                            problems.append(f'{where}: empty Lean declaration name')
                            continue
                    else:
                        absent = args[0]
                    statement = doc.semantic_body(node, omit=labels+tags)
                    out[label] = dict(where=where, kind=kind, lean=lean, notlean=absent,
                                      classification=classification, tex=digest(statement))
                except ValueError as error:
                    problems.append(str(error))
    problems.extend(collect_math(all_sources, out, digest))
    return out, problems


def review_receipts(entries, base, digest):
    receipts = {}
    for entry in entries:
        sources, _ = included_sources(entry)
        for doc in sources:
            receipts[str(doc.path.relative_to(base))] = digest(doc.text)
    return receipts


def math_coverage(entries, items):
    sources = []
    for entry in entries:
        included, _ = included_sources(entry)
        sources.extend(included)
    return coverage_report(sources, items)


def review_errors(current, recorded):
    errors = []
    for path, fingerprint in current.items():
        if recorded.get(path, {}).get('tex') != fingerprint:
            errors.append(f'{path}: manuscript text needs semantic review')
        elif not recorded[path].get('reason', '').strip():
            errors.append(f'{path}: semantic review needs a reason')
    for path in recorded.keys() - current.keys():
        errors.append(f'{path}: reviewed source is no longer included')
    return errors
