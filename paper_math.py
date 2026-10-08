"""Evidence rules for display nodes supplied by the LaTeX syntax tree."""
import re

from paper_latex import contains, is_semantic, is_display

KINDS = {'definition', 'illustrative', 'obligation', 'unmechanized'}


def collect_math(sources, items, digest):
    errors, pending = [], []
    formal_items = dict(items)
    for doc in sources:
        owners = list(filter(is_semantic, doc.all_nodes()))
        markers = [node for name in ('mathlink', 'mathclass') for node in doc.macros(name)]
        used = set()
        for block in filter(is_display, doc.all_nodes()):
            where = doc.where(block)
            adjacent = [index for index, marker in enumerate(markers)
                        if marker.pos+marker.len <= block.pos and
                        not doc.canonical(marker.pos+marker.len, block.pos).strip()]
            if any(contains(owner, block) for owner in owners):
                if adjacent:
                    errors.append(f'{where}: inherited display must not override enclosing evidence')
                continue
            if len(adjacent) != 1:
                errors.append(f'{where}: unlinked display math; add mathlink or mathclass immediately before it')
                continue
            index = adjacent[0]
            used.add(index)
            marker = markers[index]
            try:
                args = doc.args(marker)
            except ValueError as error:
                errors.append(str(error))
                continue
            label = args[0]
            # Identifier policy only; LaTeX structure is parsed by pylatexenc.
            if not re.fullmatch(r'math:[A-Za-z0-9:_-]+', label):
                errors.append(f'{where}: math marker needs a stable math: identifier')
                continue
            if label in items:
                errors.append(f'{where}: duplicate result label {label}')
                continue
            item = dict(where=where, kind='display', lean=[], notlean=None, classification=None,
                        tex=digest(doc.canonical(marker.pos, block.pos+block.len)))
            items[label] = item
            if marker.macroname == 'mathlink':
                pending.append((item, [name.strip() for name in args[1].split(',')]))
            else:
                kind, reason = args[1:]
                if kind not in KINDS or not reason:
                    errors.append(f'{where}: mathclass needs a supported kind and nonempty reason')
                elif kind == 'unmechanized':
                    item['notlean'] = reason
                else:
                    item['classification'] = dict(kind=kind, reason=reason)
        for index, marker in enumerate(markers):
            if index not in used:
                errors.append(f'{doc.where(marker)}: orphan math marker')
    for item, targets in pending:
        for target in targets:
            owner = formal_items.get(target)
            if owner is None or not owner['lean']:
                errors.append(f"{item['where']}: mathlink target {target!r} is not a Lean-backed formal result")
            else:
                item['lean'].extend(owner['lean'])
        item['lean'] = sorted(set(item['lean']))
    return errors


def coverage_report(sources, items):
    standalone = {item['where']: (label, item) for label, item in items.items() if item['kind'] == 'display'}
    report = []
    for doc in sources:
        owners = list(filter(is_semantic, doc.all_nodes()))
        for block in filter(is_display, doc.all_nodes()):
            where = doc.where(block)
            label, item = standalone.get(where, ('', None))
            inherited = False
            for owner in owners:
                if contains(owner, block):
                    labels = doc.macros('label', owner.nodelist)
                    try:
                        label = doc.args(labels[0])[0] if len(labels) == 1 else ''
                    except ValueError:
                        label = ''
                    item, inherited = items.get(label), True
                    break
            evidence = 'unlinked'
            if item:
                evidence = ('linked' if item['lean'] else 'unmechanized' if item['notlean']
                            else item['classification']['kind'] if item['classification'] else 'unlinked')
            report.append(dict(where=where, label=label, evidence=evidence, inherited=inherited))
    return report
