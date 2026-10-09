"""Parse xparse-style single-line verbatim arguments without interpreting TeX."""
from pylatexenc import latexwalker as lw
from pylatexenc.macrospec import MacroStandardArgsParser, ParsedMacroArgs


class LeanArgument(MacroStandardArgsParser):
    """Optional TeX options followed by a balanced-brace or delimited raw term."""
    def __init__(self):
        super().__init__('[')

    def parse_args(self, w, pos, parsing_state=None):
        start = pos
        options, _, length = super().parse_args(w, pos, parsing_state=parsing_state)
        pos += length
        while pos < len(w.s) and w.s[pos] in ' \t':
            pos += 1
        if pos >= len(w.s) or w.s[pos].isspace():
            raise ValueError('Lean source needs a single-line verbatim argument')
        opening = w.s[pos]
        closing = '}' if opening == '{' else opening
        if opening.isalnum() or opening in '\\%}':
            raise ValueError('Lean source needs braces or a punctuation delimiter')
        end, depth = pos + 1, 1
        while end < len(w.s):
            char = w.s[end]
            if char in '\r\n':
                raise ValueError('Lean source arguments must stay on one source line')
            if opening == '{' and char == '{':
                depth += 1
            if char == closing:
                depth -= 1
                if depth == 0:
                    break
            end += 1
        if end == len(w.s):
            raise ValueError('unclosed Lean source argument')
        body = w.make_node(lw.LatexCharsNode, parsing_state=parsing_state,
                           chars=w.s[pos+1:end], pos=pos+1, len=end-pos-1)
        group = w.make_node(lw.LatexGroupNode, parsing_state=parsing_state,
                            delimiters=(opening, closing), nodelist=[body], pos=pos, len=end-pos+1)
        return ParsedMacroArgs(argspec='[{', argnlist=[options.argnlist[0], group]), start, end+1-start
