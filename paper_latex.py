"""Strict LaTeX syntax-tree adapter for the paper evidence checker.

pylatexenc parses nesting, arguments, comments and math. This adapter registers
our vocabulary and suppresses traversal of declarations/literal bodies. It does
not expand macros or evaluate TeX conditionals.
"""
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    from pylatexenc import latexwalker as lw
    from pylatexenc.macrospec import EnvironmentSpec, MacroSpec, MacroStandardArgsParser, ParsedVerbatimArgs
except ModuleNotFoundError as error:
    raise SystemExit('Paper checker dependencies are missing. Install tidy-lean/requirements.txt '
                     'or run with uv run --with-requirements tidy-lean/requirements.txt python.') from error

from paper_lean_syntax import LeanArgument

SEMANTIC_ENVS = ('definition', 'lemma', 'proposition', 'theorem', 'corollary',
                 'contract', 'obligation', 'proposal', 'paperclaim')
DISPLAY_ENVS = ('equation', 'align', 'alignat', 'gather', 'multline', 'displaymath', 'eqnarray', 'flalign')
LITERAL_ENVS = ('Verbatim', 'verbatim', 'lstlisting', 'minted')
DECLARATIONS = {'newcommand', 'renewcommand', 'providecommand', 'DeclareRobustCommand',
                'newenvironment', 'renewenvironment', 'newtheorem', 'def', 'gdef', 'edef', 'xdef'}
EVIDENCE_ARGS = {'label': 1, 'lean': 1, 'notlean': 1, 'paperstatus': 2,
                 'mathlink': 2, 'mathclass': 3, 'input': 1, 'include': 1}


class LiteralBody(MacroStandardArgsParser):
    """Environment-specific raw delimiter, as used by TeX's verbatim readers."""
    def __init__(self, name):
        super().__init__('')
        self.name = name

    def parse_args(self, w, pos, parsing_state=None):
        end = w.s.find('\\end{' + self.name + '}', pos)
        if end < 0:
            raise lw.LatexWalkerParseError(s=w.s, pos=pos, msg='Unclosed literal environment ' + self.name)
        node = w.make_node(lw.LatexCharsNode, parsing_state=parsing_state,
                           chars=w.s[pos:end], pos=pos, len=end-pos)
        return ParsedVerbatimArgs(verbatim_chars_node=node), pos, end-pos


class VerbArgument(MacroStandardArgsParser):
    def __init__(self):
        super().__init__('')

    def parse_args(self, w, pos, parsing_state=None):
        start = pos
        if pos < len(w.s) and w.s[pos] == '*':
            pos += 1
        if pos >= len(w.s) or w.s[pos].isspace():
            raise lw.LatexWalkerParseError(s=w.s, pos=pos, msg='Missing verb delimiter')
        delimiter = w.s[pos]
        end = w.s.find(delimiter, pos+1)
        if end < 0 or '\n' in w.s[pos:end]:
            raise lw.LatexWalkerParseError(s=w.s, pos=pos, msg='Unclosed verb literal')
        node = w.make_node(lw.LatexCharsNode, parsing_state=parsing_state,
                           chars=w.s[pos+1:end], pos=pos+1, len=end-pos-1)
        return ParsedVerbatimArgs(verbatim_chars_node=node), start, end+1-start


def context():
    result = lw.get_default_latex_context_db()
    macros = [MacroSpec(name, '{' * count) for name, count in EVIDENCE_ARGS.items()]
    macros += [MacroSpec('paperexpr', '[{'), MacroSpec('leanformula', '[{'),
               MacroSpec('leanexpr', args_parser=LeanArgument()),
               MacroSpec('leanname', args_parser=LeanArgument())]
    macros.append(MacroSpec('verb', args_parser=VerbArgument()))
    environments = [EnvironmentSpec(name, '[') for name in SEMANTIC_ENVS]
    environments.append(EnvironmentSpec('leancontext', args_parser=LeanArgument()))
    environments += [EnvironmentSpec(name + star, '', is_math_mode=True)
                     for name in DISPLAY_ENVS for star in ('', '*')]
    environments += [EnvironmentSpec(name, args_parser=LiteralBody(name)) for name in LITERAL_ENVS]
    result.add_context_category('paper-evidence', macros=macros, environments=environments, prepend=True)
    return result


def literal(node):
    return (isinstance(node, lw.LatexEnvironmentNode) and node.environmentname in LITERAL_ENVS or
            isinstance(node, lw.LatexMacroNode) and node.macroname == 'verb')


def children(node):
    if literal(node) or isinstance(node, lw.LatexMacroNode) and node.macroname in DECLARATIONS:
        return []
    result = list(getattr(node, 'nodelist', None) or [])
    args = getattr(node, 'nodeargd', None)
    if args:
        result += [arg for arg in args.argnlist if arg is not None]
    return result


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(children(node))


def is_semantic(node):
    return isinstance(node, lw.LatexEnvironmentNode) and node.environmentname in SEMANTIC_ENVS


def is_display(node):
    return (isinstance(node, lw.LatexMathNode) and node.displaytype == 'display' or
            isinstance(node, lw.LatexEnvironmentNode) and node.environmentname.rstrip('*') in DISPLAY_ENVS)


def contains(outer, inner):
    return outer.pos <= inner.pos and inner.pos + inner.len <= outer.pos + outer.len


@dataclass
class Document:
    path: object
    text: str
    nodes: list
    walker: object
    errors: list
    # The syntax tree is fixed once parsed: the node list and the masked
    # text (canonical) are computed once and reused by every query.
    _all: list = field(default=None, repr=False, compare=False)
    _masked: str = field(default=None, repr=False, compare=False)

    def where(self, node):
        pos = node if isinstance(node, int) else node.pos
        return f'{self.path}:{self.text.count(chr(10), 0, pos)+1}:{pos-self.text.rfind(chr(10), 0, pos)}'

    def all_nodes(self):
        if self._all is None:
            self._all = list(walk(self.nodes))
        return self._all

    def macros(self, name, nodes=None):
        return [n for n in walk(self.nodes if nodes is None else nodes)
                if isinstance(n, lw.LatexMacroNode) and n.macroname == name]

    def args(self, node):
        args = node.nodeargd.argnlist if node.nodeargd else []
        count = EVIDENCE_ARGS[node.macroname]
        if len(args) != count or any(not isinstance(arg, lw.LatexGroupNode) or
                                     arg.delimiters != ('{', '}') for arg in args):
            raise ValueError(f'{self.where(node)}: {node.macroname} needs {count} braced argument(s)')
        return [self.canonical(arg.pos+1, arg.pos+arg.len-1).strip() for arg in args]

    def masked(self):
        """The text with comments blanked and literal examples escaped, one
        character for one, so that every slice of it is the canonical form
        of that slice of the source."""
        if self._masked is None:
            masked = list(self.text)
            for node in self.all_nodes():
                lo, hi = node.pos, node.pos+node.len
                if isinstance(node, lw.LatexCommentNode):
                    # Comment post-space may contain a newline; keep source positions.
                    masked[lo:hi] = ['\n' if c == '\n' else ' ' for c in self.text[lo:hi]]
                elif literal(node):
                    masked[lo:hi] = self.text[lo:hi].replace('\\', '⌿').replace('%', '％').replace('$', '＄')
            self._masked = ''.join(masked)
        return self._masked

    def canonical(self, start=0, end=None, omit=()):
        """Source-based fingerprints: ignore comments, retain literal examples."""
        if end is None:
            end = len(self.text)
        masked = list(self.masked()[start:end])
        for node in omit:
            lo, hi = max(start, node.pos), min(end, node.pos+node.len)
            if hi > lo:
                masked[lo-start:hi-start] = ['\n' if c == '\n' else ' ' for c in self.text[lo:hi]]
        return ''.join(masked)

    def semantic_body(self, node, omit=()):
        # Include the optional title, as the previous statement fingerprints did.
        opening = self.walker.get_token(node.pos)
        start = opening.pos + opening.len
        contents = children(node)
        end = max([start] + [n.pos+n.len for n in contents])
        return self.canonical(start, end, omit)


# A directory for parsed documents, set by a caller that may reuse them
# across runs (check_paper.py): a document depends only on its text and on
# this parser, so one is read back rather than parsed again while neither
# changes.
CACHE_DIR = None


def _cache_key(text, path):
    import hashlib
    salt = Path(__file__).read_text() + getattr(lw, '__version__', '') + str(path)
    return hashlib.sha256((salt + '\0' + text).encode()).hexdigest()


@lru_cache(maxsize=256)
def parse(text, path):
    if CACHE_DIR is None:
        return parse_fresh(text, path)
    import pickle
    cached = Path(CACHE_DIR) / (_cache_key(text, path) + '.pkl')
    if cached.is_file():
        try:
            return pickle.loads(cached.read_bytes())
        except Exception:  # a stale or truncated pickle is parsed again
            pass
    doc = parse_fresh(text, path)
    doc.all_nodes()
    doc.masked()
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    temporary = cached.with_suffix('.tmp%d' % os.getpid())
    temporary.write_bytes(pickle.dumps(doc, protocol=pickle.HIGHEST_PROTOCOL))
    temporary.replace(cached)
    return doc


def parse_fresh(text, path):
    walker = lw.LatexWalker(text, latex_context=context(), tolerant_parsing=False)
    try:
        nodes, pos, length = walker.get_latex_nodes(pos=0)
        if pos + length != len(text):
            raise ValueError('parser did not consume the full source')
    except (lw.LatexWalkerParseError, ValueError) as error:
        return Document(path, text, [], walker, [f'{path}: LaTeX parse error (environment/math structure): {error}'])
    doc = Document(path, text, nodes, walker, [])
    all_nodes = doc.all_nodes()
    for node in all_nodes:
        if isinstance(node, lw.LatexMacroNode) and node.macroname in {'def', 'gdef', 'edef', 'xdef'}:
            doc.errors.append(f'{doc.where(node)}: raw TeX definitions are unsupported; use newcommand')
        if is_semantic(node) and any(is_semantic(n) for n in walk(children(node))):
            doc.errors.append(f'{doc.where(node)}: nested semantic environments are unsupported')
        if is_display(node) and any(is_display(n) for n in walk(children(node))):
            doc.errors.append(f'{doc.where(node)}: nested display math is unsupported')
        if is_display(node) and any(is_semantic(n) for n in walk(children(node))):
            doc.errors.append(f'{doc.where(node)}: display crosses a semantic environment boundary')
    return doc
