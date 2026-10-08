"""Paper-root reachability over elaborated Lean declaration dependencies.

Every authored project declaration is an orphan candidate. Generated declarations
participate in reachability but are not separate pruning units. Lean's source
references supplement elaborated dependencies, which can erase tactic references.
Exceptional retention requires an explicit reason and remains visible in the audit.
"""
import json
from collections import defaultdict
from pathlib import Path


def parse_inventory(output):
    modules, nodes, ended = None, {}, False
    for line in output.splitlines():
        if line.startswith('@@INVENTORY_BEGIN '):
            if modules is not None:
                raise ValueError('duplicate Lean inventory header')
            modules = json.loads(line.split(' ', 1)[1])
            if not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):
                raise ValueError('invalid Lean module inventory')
        elif line.startswith('@@NODE '):
            if modules is None or ended:
                raise ValueError('Lean node outside inventory')
            node = json.loads(line.split(' ', 1)[1])
            if (not isinstance(node, dict) or not isinstance(node.get('name'), str)
                    or node.get('module') not in modules
                    or not isinstance(node.get('dependencies'), list)
                    or not all(isinstance(n, str) for n in node['dependencies'])
                    or node.get('kind') not in {'theorem', 'definition', 'structure', 'inductive'}
                    or type(node.get('proof')) is not bool or type(node.get('line')) is not int):
                raise ValueError('invalid Lean declaration inventory')
            if node['name'] in nodes:
                raise ValueError('duplicate Lean declaration: ' + node['name'])
            nodes[node['name']] = node
        elif line == '@@INVENTORY_END':
            if modules is None or ended:
                raise ValueError('unexpected Lean inventory end')
            ended = True
    if modules is None or not ended:
        raise ValueError('incomplete Lean dependency inventory')
    return set(modules), nodes


def reachable(nodes, roots):
    seen, pending = set(), list(roots)
    while pending:
        name = pending.pop()
        if name in seen or name not in nodes:
            continue
        seen.add(name)
        pending.extend(nodes[name]['dependencies'])
    return seen


def source_inventory(proofs, modules, nodes, index_root=None):
    """Identify authored declarations and add Lean's resolved source references.

    The .ilean declaration table separates authored structures from their
    generated projections, constructors, recursors and extensionality lemmas.
    Its references include explicit tactic arguments erased by elaboration.
    Implicit automation use is not recorded; pruning still requires a rebuild.
    """
    index_root = Path(index_root or Path(proofs, '.lake/build/lib/lean'))
    enriched = {name: dict(node, authored=False,
                           dependencies=list(node['dependencies']), source_dependencies=[])
                for name, node in nodes.items()}
    for module in sorted(modules):
        relative = Path(*module.split('.'))
        index = index_root / relative.with_suffix('.ilean')
        source = Path(proofs) / relative.with_suffix('.lean')
        if not index.is_file() or not source.is_file():
            raise ValueError(f'{module}: missing Lean source index; run lake build')
        if source.stat().st_mtime_ns > index.stat().st_mtime_ns:
            raise ValueError(f'{module}: stale Lean source index; run lake build')
        data = json.loads(index.read_text())
        if (data.get('version') != 5 or data.get('module') != module
                or not isinstance(data.get('decls'), dict)
                or not isinstance(data.get('references'), dict)):
            raise ValueError(f'{module}: unsupported Lean source index')
        for name in data['decls']:
            if name not in enriched or enriched[name]['module'] != module:
                raise ValueError(f'{module}: authored declaration missing from environment: {name}')
            enriched[name]['authored'] = True
        for identifier, reference in data['references'].items():
            target = json.loads(identifier).get('c', {}).get('n')
            if target not in enriched:
                continue
            for usage in reference['usages']:
                owner = usage[4] if len(usage) == 5 else None
                if owner in enriched and owner != target:
                    enriched[owner]['dependencies'].append(target)
                    enriched[owner]['source_dependencies'].append(target)
    return enriched


def audit(nodes, modules, paper_roots, source_modules, exceptions=None):
    exceptions = {} if exceptions is None else exceptions
    errors = []
    if not isinstance(exceptions, dict) or set(exceptions) - {'roots', 'modules'}:
        raise ValueError('orphan exceptions must contain only roots and modules')
    retained = {}
    for kind in ('roots', 'modules'):
        entries = exceptions.get(kind, {})
        if not isinstance(entries, dict):
            raise ValueError('orphan exception groups must be objects')
        for name, reason in entries.items():
            if not isinstance(name, str) or not isinstance(reason, str) or not reason.strip():
                raise ValueError('orphan exceptions require names and nonempty reasons')
        retained[kind] = entries
    linked = reachable(nodes, paper_roots)
    for name in retained['roots']:
        if name not in nodes:
            errors.append('orphan-roots.json: unknown standalone declaration ' + name)
        elif not nodes[name]['authored']:
            errors.append('orphan-roots.json: standalone root is not authored: ' + name)
        elif name in linked:
            errors.append('orphan-roots.json: redundant standalone root ' + name)
    for module in retained['modules']:
        if module not in source_modules:
            errors.append('orphan-roots.json: unknown excluded source module ' + module)
        elif module in modules:
            errors.append('orphan-roots.json: redundant imported-module exclusion ' + module)
    connected = linked | reachable(nodes, retained['roots'])
    declarations = sorted(name for name, node in nodes.items() if node['authored'])
    proofs = [name for name in declarations if nodes[name]['proof']]
    orphans = [name for name in declarations if name not in linked]
    orphaned_proofs = [name for name in orphans if nodes[name]['proof']]
    dependents = defaultdict(set)
    for name, node in nodes.items():
        for dependency in node['dependencies']:
            if dependency in nodes and dependency != name:
                dependents[dependency].add(name)
    missing = sorted(set(source_modules) - modules)
    by_module = defaultdict(list)
    for name in orphans:
        if name in connected:
            continue
        by_module[nodes[name]['module']].append(name)
    for module, names in sorted(by_module.items()):
        preview = ', '.join(names[:5])
        if len(names) > 5:
            preview += f', ... ({len(names)} total)'
        errors.append(f'{module}: orphaned Lean declarations: {preview}')
    for module in missing:
        if module not in retained['modules']:
            errors.append(f'{module}: source module is not imported by DeadlockProofs; declaration coverage unknown')
    report = {'paper_connected': sorted(linked), 'standalone_connected': sorted(connected - linked),
              'declaration_inventory': declarations,
              'declaration_kinds': {name: nodes[name]['kind'] for name in declarations},
              'proof_inventory': proofs,
              'orphaned_declarations': orphans,
              'orphaned_proofs': orphaned_proofs, 'unimported_modules': missing,
              'unused_orphaned_declarations': [name for name in orphans if not dependents[name]],
              'unused_orphaned_proofs': [name for name in orphaned_proofs if not dependents[name]],
              'retained_orphans': sorted(set(orphans) & connected),
              'orphan_dependents': {name: sorted(dependents[name]) for name in orphans},
              'dependencies': {name: sorted(set(node['dependencies']))
                               for name, node in sorted(nodes.items())},
              'source_dependencies': {name: sorted(set(node.get('source_dependencies', [])))
                                      for name, node in sorted(nodes.items())
                                      if node.get('source_dependencies')},
              'orphan_locations': {name: {'module': nodes[name]['module'], 'line': nodes[name]['line']}
                                   for name in orphans},
              'exceptions': retained, 'errors': errors}
    return report


def source_modules(proofs):
    return {'.'.join(path.relative_to(proofs).with_suffix('').parts)
            for path in Path(proofs, 'DeadlockProofs').rglob('*.lean')} | {'DeadlockProofs'}
