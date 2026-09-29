"""Strict offline expansion of the frozen Hesperian Midwives template subset.

No network, source rewriting, clinical interpretation or content admission.
Unsupported markup is an error, not silently removed text.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from html import escape
import re
from urllib.parse import quote


class RenderError(ValueError):
    pass


def split_top(text, separator='|'):
    """Split template arguments while respecting nested braces and wiki links."""
    parts, stack, start, i = [], [], 0, 0
    while i < len(text):
        # MediaWiki's preprocessor treats line-start headings as their own
        # node; their equals signs do not name an enclosing template parameter.
        # https://doc.wikimedia.org/mediawiki-core/1.45.0/php/Preprocessor__Hash_8php_source.html
        if separator == '=' and not stack and (i == 0 or text[i - 1] == '\n') and text.startswith('==', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text.startswith('{{{', i):
            stack.append('}}}'); i += 3
        elif text.startswith('{{', i):
            stack.append('}}'); i += 2
        elif text.startswith('[[', i):
            stack.append(']]'); i += 2
        elif stack and text.startswith(stack[-1], i):
            i += len(stack.pop())
        elif text.startswith(separator, i) and not stack:
            parts.append(text[start:i]); i += len(separator); start = i
        else:
            i += 1
    if stack:
        raise RenderError('Unclosed nested markup in template arguments')
    return parts + [text[start:]]


def brace_at(text, start):
    opening = 3 if text.startswith('{{{', start) else 2
    stack, i = [opening], start + opening
    while i < len(text):
        if text.startswith('}' * stack[-1], i):
            i += stack.pop()
            if not stack:
                return opening, text[start + opening:i - opening], i
        elif text.startswith('{{{', i):
            stack.append(3); i += 3
        elif text.startswith('{{', i):
            stack.append(2); i += 2
        else:
            i += 1
    raise RenderError('Unclosed template or parameter')


def transclusion(text):
    text = re.sub(r'<noinclude\b[^>]*>.*?</noinclude\s*>', '', text, flags=re.I | re.S)
    return re.sub(r'</?includeonly\s*>', '', text, flags=re.I)


class Expander:
    def __init__(self, templates, *, max_output=2 * 1024 * 1024, max_calls=30000, literal_cases=()):
        self.templates = {name.removeprefix('Template:').casefold(): transclusion(text) for name, text in templates.items()}
        self.max_output, self.max_calls = max_output, max_calls
        self.literal_cases = list(literal_cases)

    def page(self, title, revision, text):
        original_bytes = text.encode()
        self.calls = 0
        self.trace = []
        self.literal_preservations = []
        self.title, self.revision = title, revision
        self.namespace, _, self.name = title.partition(':')
        if not self.name:
            self.namespace, self.name = '', title
        self.display_title = self.name
        # Protect literal braces/bars in nowiki from the template parser.
        text = re.sub(r'<nowiki>(.*?)</nowiki>', lambda m: escape(m[1]).replace('{', '&#123;').replace('}', '&#125;').replace('|', '&#124;'), text, flags=re.I | re.S)
        text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        result = self.expand(text, {}, 0)
        if len(result.encode()) > self.max_output:
            raise RenderError('Expanded page exceeds byte bound')
        if '{{' in result:
            raise RenderError('Unresolved opening braces after expansion')
        if '}}' in result:
            # Literal punctuation is allowed only by an exact source-bound
            # publisher-render comparison. The characters remain unchanged.
            original = original_bytes
            matches = [case for case in self.literal_cases
                       if case.get('title') == title
                       and case.get('payload_sha1') == hashlib.sha1(original).hexdigest()
                       and case.get('whole_response_sha256') == hashlib.sha256(b'\n\n\n\n' + original).hexdigest()
                       and case.get('literal_hex') == '7d7d'
                       and original[case.get('payload_byte_offset', -1):case.get('payload_byte_offset', -1) + 2] == b'}}'
                       and re.fullmatch(r'[0-9a-f]{64}', case.get('comparison_report_sha256', ''))]
            if len(matches) != 1 or result.count('}}') != 1:
                raise RenderError('Unresolved closing braces after expansion')
            self.literal_preservations = matches
        return result

    def expand(self, text, params, depth):
        if depth > 40:
            raise RenderError('Template recursion bound exceeded')
        parts, cursor = [], 0
        while True:
            start = text.find('{{', cursor)
            if start < 0:
                parts.append(text[cursor:]); break
            parts.append(text[cursor:start])
            opening, inner, end = brace_at(text, start)
            self.calls += 1
            if self.calls > self.max_calls:
                raise RenderError('Template expansion count exceeded')
            args = split_top(inner)
            if opening == 3:
                key = self.expand(args[0], params, depth + 1).strip()
                if key in params:
                    value = params[key]
                elif len(args) > 1:
                    value = self.expand('|'.join(args[1:]), params, depth + 1)
                else:
                    raise RenderError('Missing template parameter ' + key + ' in ' + (self.trace[-1] if self.trace else 'page'))
            else:
                value = self.call(args, params, depth + 1)
            parts.append(value)
            if sum(map(len, parts)) > self.max_output:
                raise RenderError('Expansion exceeds bounded page size')
            cursor = end
        return ''.join(parts)

    def call(self, args, params, depth):
        head = self.expand(args[0], params, depth).strip()
        prefix, sep, rest = head.partition(':')
        evaluate = lambda s: self.expand(s, params, depth)
        if prefix == '#if':
            if not sep or len(args) not in {2, 3}:
                raise RenderError('Unsupported #if arity')
            return evaluate(args[1] if rest.strip() else (args[2] if len(args) == 3 else ''))
        if prefix == '#switch':
            wanted, default, fallthrough = rest.strip(), '', False
            for item in args[1:]:
                pair = split_top(item, '=')
                if len(pair) == 1:
                    fallthrough = fallthrough or evaluate(pair[0]).strip() == wanted
                    continue
                key, value = evaluate(pair[0]).strip(), '='.join(pair[1:])
                if key == '#default':
                    default = value
                elif key == wanted or fallthrough:
                    return evaluate(value)
                fallthrough = False
            return evaluate(default)
        if prefix == '#time':
            if rest.strip() != 'd M Y' or len(args) != 2:
                raise RenderError('Unsupported revision date formatting')
            value = evaluate(args[1]).strip()
            date = datetime.strptime(value, '%Y%m%d%H%M%S')
            return f'{date.day:02d} {"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[date.month-1]} {date.year}'
        if prefix == '#tag':
            if rest.strip() != 'html' or len(args) != 2:
                raise RenderError('Unsupported #tag construct')
            return evaluate(args[1])
        if prefix == 'DISPLAYTITLE':
            self.display_title = rest
            return ''
        if prefix.casefold() == 'fullurl':
            if len(args) > 2:
                raise RenderError('Unsupported fullurl construct')
            return 'https://en.hesperian.org/w/index.php?title=' + quote(rest.replace(' ', '_'), safe='') + ('&' + evaluate(args[1]) if len(args) == 2 else '')
        magic = {'NAMESPACE': self.namespace, 'PAGENAME': self.name, 'FULLPAGENAME': self.title,
                 'REVISIONTIMESTAMP': datetime.fromisoformat(self.revision['timestamp'].replace('Z', '+00:00')).strftime('%Y%m%d%H%M%S'), '!': '|'}
        if head in magic and len(args) == 1:
            return magic[head]
        name = head.removeprefix('Template:').casefold()
        if name not in self.templates:
            raise RenderError('Unknown template/function: ' + head)
        values, position = {}, 1
        for item in args[1:]:
            pair = split_top(item, '=')
            if len(pair) > 1:
                key = evaluate(pair[0]).strip()
                values[key] = evaluate('='.join(pair[1:])).strip()
            else:
                values[str(position)] = evaluate(item)
                position += 1
        # Publisher LinkButton's omitted third parameter is a CSS class only.
        # Its visible text and href are still mandatory; record this explicit case.
        if name == 'linkbutton':
            values.setdefault('3', '')
        self.trace.append(head)
        try:
            return self.expand(self.templates[name], values, depth)
        finally:
            self.trace.pop()
