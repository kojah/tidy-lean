"""Paper-root reachability over elaborated Lean declaration dependencies.

Every authored project declaration is an orphan candidate. Generated declarations
participate in reachability but are not separate pruning units. Lean's source
references supplement elaborated dependencies, which can erase tactic references.
Exceptional retention requires an explicit reason and remains visible in the audit.
"""
import json
from pathlib import Path
from lean_orphans import audit, reachable


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
                    or type(node.get('proof')) is not bool or type(node.get('line')) is not int
                    or type(node.get('declared_inductive', False)) is not bool):
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


def source_inventory(proofs, modules, nodes, index_root=None):
    """Identify authored declarations and add Lean's resolved source references.

    The .ilean declaration table separates authored structures from their
    generated projections, constructors, recursors and extensionality lemmas.
    Its references include explicit tactic arguments erased by elaboration.
    Implicit automation use is not recorded; pruning still requires a rebuild.
    """
    index_root = Path(index_root or Path(proofs, '.lake/build/lib/lean'))
    enriched = {name: dict(node, authored=node.get('declared_inductive', False),
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


def source_modules(proofs):
    return {'.'.join(path.relative_to(proofs).with_suffix('').parts)
            for path in Path(proofs, 'DeadlockProofs').rglob('*.lean')} | {'DeadlockProofs'}
