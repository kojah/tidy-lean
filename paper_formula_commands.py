"""Evidence carried by declaration-backed LaTeX commands."""
import re

def options(text: str) -> dict[str, str]:
    """Split key/value fields at top-level commas, retaining braced values."""
    fields, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                raise ValueError('unbalanced formula options')
        elif char == ',' and depth == 0:
            fields.append(text[start:i])
            start = i + 1
    if depth:
        raise ValueError('unbalanced formula options')
    fields.append(text[start:])
    result = {}
    for field in fields:
        if not field.strip():
            continue
        key, separator, value = field.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or key not in {'label', 'title', 'names', 'layout'} or key in result:
            raise ValueError(f'unknown, duplicate or malformed formula option: {key!r}')
        if value.startswith('{') and value.endswith('}'):
            value = value[1:-1]
        value = ' '.join(value.split())
        if any(c in value for c in '{}\\%'):
            raise ValueError(f'formula option {key} must be plain metadata')
        result[key] = value
    if not re.fullmatch(r'[A-Za-z0-9:-]+', result.get('label', '')):
        raise ValueError('leanformula requires a stable label')
    title = result.get('title', '')
    if not title or any(not (c.isalnum() or c in ' ,-()') for c in title):
        raise ValueError('leanformula requires a plain-text title')
    if result.get('layout', 'auto') not in {'auto', 'multiline'}:
        raise ValueError('formula layout must be auto or multiline')
    seen = set()
    for pair in result.get('names', '').split():
        parts = pair.split('=')
        if len(parts) != 2 or any(not value.isidentifier() for value in parts) or parts[0] in seen:
            raise ValueError(f'invalid or duplicate binder name option: {pair}')
        seen.add(parts[0])
    return result



def collect_formulas(doc, out, digest):
    problems = []
    for node in doc.macros('leanformula'):
        try:
            args = node.nodeargd.argnlist
            if len(args) != 2 or args[0] is None or getattr(args[1], 'delimiters', None) != ('{', '}'):
                raise ValueError('leanformula needs options and a declaration')
            settings = options(doc.canonical(args[0].pos+1, args[0].pos+args[0].len-1))
            name = doc.canonical(args[1].pos+1, args[1].pos+args[1].len-1).strip()
            if not name or any(not part.isidentifier() for part in name.split('.')):
                raise ValueError('invalid Lean declaration name')
            label = settings['label']
            if label in out:
                raise ValueError(f'duplicate result label {label}')
            out[label] = dict(where=doc.where(node), kind='formula', lean=[name], notlean=None,
                              classification=None, tex=digest(doc.canonical(node.pos, node.pos+node.len)))
        except ValueError as error:
            problems.append(f'{doc.where(node)}: {error}')
    return problems
