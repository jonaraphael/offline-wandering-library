"""Bounded, offline ordinary HTML for already expanded Midwives wikitext.

The converter preserves source words, illustrations and inline positioning.
Its output is a review candidate: unsupported syntax and unresolved local
dependencies are errors, and publishing/admission is deliberately absent.
"""
from __future__ import annotations

from collections import Counter
from html import escape, unescape
from html.parser import HTMLParser
import math
import re
from urllib.parse import quote, unquote, urlsplit

from .midwives_wikitext import RenderError, split_top

MAX_PAGE_BYTES = 2 * 1024 * 1024
CSS = '''body{font:18px/1.5 system-ui,sans-serif;color:#161616;background:#fff;margin:0 auto;padding:1rem;max-width:1080px}
main{overflow-x:auto}a{color:#0645ad}.online:after{content:" [online]";font-size:.75em}img{vertical-align:middle}
table{border-collapse:collapse;max-width:none}td,th{vertical-align:top}h1,h2,h3,h4,h5,h6{line-height:1.3;clear:none}
.floatleft{float:left;margin:0 .8rem .4rem 0}.floatright{float:right;margin:0 0 .4rem .8rem}.center{text-align:center}
.thumbcaption{font-size:.9em;text-align:left}.thumb,.frame{border:1px solid #aaa;padding:.4rem;background:#fafafa}
.callout,.howto,.box{padding:.8rem;border:1px solid #555;margin:.8rem 0}.warning,.important{border:2px solid #8c4400;background:#fff5df}
#cautionpregnant,#cautionbreastfeeding{padding:.5rem;border:2px solid #8c4400;font-weight:bold;background:#fff5df}
.transport{border:3px solid #900;font-weight:bold}.rtl-only{display:none}.sidedoc-controls,.publisher-mobile-selector{display:none}
#sidetoc{display:block;position:static;max-width:100%;padding:.6rem;border:1px solid #aaa;background:#f7f7f7}
.alphaselect ul{display:flex;flex-wrap:wrap;gap:.6rem;list-style:none;padding:0}.sources{clear:both}details{margin:1rem 0}
.source-provenance{clear:both;border-top:1px solid #aaa;margin-top:2rem;font-size:.8em}pre{white-space:pre-wrap}
.green,.greenbox{background:#eef6df}.navlink{clear:both;padding:.6rem 0}figure{margin:.4rem 0}.review-notice{border:1px solid #777;padding:.6rem;background:#eee}
'''


def normal_title(value):
    value = unescape(unquote(value)).replace('_', ' ').strip()
    if ':' in value:
        namespace, rest = value.split(':', 1)
        return namespace + ':' + (rest[:1].upper() + rest[1:])
    return value[:1].upper() + value[1:]


def plain_text(html):
    class Plain(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True); self.data = []
        def handle_data(self, data):
            self.data.append(data)
    parser = Plain(); parser.feed(html)
    return ''.join(parser.data)


def anchor(value):
    return unescape(unquote(value)).strip().replace(' ', '_')


class OrdinaryHTML:
    def __init__(self, pages, images):
        self.pages = {normal_title(p['title']): ('index.html' if p['title'] == 'A Book for Midwives' else f"page-{p['pageid']}.html")
                      for p in pages if not p['title'].startswith('Template:')}
        self.images = {normal_title(row['title'].replace('Image:', 'File:', 1)): row for row in images}
        if len(self.pages) > 300 or len(self.images) > 2500:
            raise RenderError('Reader inventory exceeds its frozen limits')

    def href(self, target):
        target = unescape(target).strip()
        if target.startswith(('https://', 'http://', 'mailto:')):
            self.external.add(target)
            return target, True
        page, marker, fragment = target.partition('#')
        page = normal_title(page) if page else self.current
        if page in self.pages:
            suffix = '#' + quote(anchor(fragment), safe='-._~') if marker else ''
            value = self.pages[page] + suffix
            self.links.append({'page': page, 'fragment': anchor(fragment) if marker else ''})
            return value, False
        if page.startswith('A Book for Midwives:'):
            raise RenderError('Uncaptured canonical book page: ' + page)
        match = re.match(r'^(en|es|fr|ht):(.*)', page)
        host, remote = (match[1], match[2]) if match else ('en', page)
        value = 'https://' + host + '.hesperian.org/hhg/' + quote(remote.replace(' ', '_'), safe=':()')
        if marker:
            value += '#' + quote(anchor(fragment), safe='-._~')
        self.external.add(value)
        return value, True

    def link(self, target, label):
        href, online = self.href(target)
        return '<a href="' + escape(href, quote=True) + '"' + (' class="online"' if online else '') + '>' + label + '</a>'

    def image(self, parts):
        name = normal_title(re.sub(r'^(?:Image|File):', 'File:', parts[0], flags=re.I))
        if name not in self.images:
            raise RenderError('Uncaptured original illustration: ' + name)
        row = self.images[name]
        opts = {'align': '', 'border': False, 'frame': False, 'alt': '', 'caption': '', 'link': None, 'width': None, 'height': None}
        for option in parts[1:]:
            value = option.strip()
            if value in {'left', 'right', 'center', 'none'}:
                opts['align'] = value
            elif value in {'thumb', 'thumbnail', 'frame'}:
                opts['frame'] = True
            elif value in {'border', 'frameless'}:
                opts['border'] = value == 'border'
            elif re.fullmatch(r'(?:\d+)?x?\d+px', value):
                dim = value[:-2].split('x')
                opts['width'], opts['height'] = ((int(dim[0]), None) if len(dim) == 1 else (int(dim[0]) if dim[0] else None, int(dim[1])))
            elif value.startswith('alt='):
                opts['alt'] = value[4:]
            elif value.startswith('link='):
                opts['link'] = value[5:]
            elif value.startswith(('class=', 'page=', 'upright')):
                raise RenderError('Unsupported image option: ' + value)
            elif value:
                opts['caption'] = value
        width, height = row['info']['width'], row['info']['height']
        ratios = [1]
        if opts['width'] is not None:
            ratios.append(opts['width'] / width)
        if opts['height'] is not None:
            ratios.append(opts['height'] / height)
        ratio = min(ratios)
        width, height = max(1, math.floor(width * ratio + .5)), max(1, math.floor(height * ratio + .5))
        path = 'images/' + row['source_id'] + '.png'
        self.used_images.add(name)
        attrs = {'src': path, 'width': str(width), 'height': str(height), 'alt': plain_text(opts['alt']), 'loading': 'lazy'}
        if opts['caption']:
            attrs['title'] = plain_text(opts['caption'])
        if opts['border']:
            attrs['style'] = 'border:1px solid #777'
        html = '<img ' + ' '.join(k + '="' + escape(v, quote=True) + '"' for k, v in attrs.items()) + '>'
        if opts['link'] is None:
            html = '<a href="' + path + '">' + html + '</a>'
        elif opts['link']:
            html = self.link(opts['link'], html)
        classes = {'left': 'floatleft', 'right': 'floatright', 'center': 'center'}.get(opts['align'], '')
        if opts['frame']:
            html += '<div class="thumbcaption">' + self.inline(opts['caption']) + '</div>'
            classes += ' thumb'
        return '<span class="' + classes.strip() + '" style="display:inline-block;width:' + str(width) + 'px">' + html + '</span>'

    def wiki_links(self, text):
        output, cursor = [], 0
        while True:
            start = text.find('[[', cursor)
            if start < 0:
                output.append(text[cursor:]); break
            output.append(text[cursor:start]); level, i = 1, start + 2
            while i < len(text) and level:
                if text.startswith('[[', i): level += 1; i += 2
                elif text.startswith(']]', i): level -= 1; i += 2
                else: i += 1
            if level:
                raise RenderError('Unclosed wiki link')
            parts = split_top(text[start + 2:i - 2])
            if re.match(r'^(?:File|Image):', parts[0].strip(), re.I):
                output.append(self.image(parts))
            else:
                if len(parts) > 2:
                    raise RenderError('Ambiguous wiki-link label')
                label = self.inline(parts[1]) if len(parts) == 2 else escape(parts[0].replace('_', ' '))
                output.append(self.link(parts[0], label))
            cursor = i
        return ''.join(output)

    def inline(self, text):
        text = self.wiki_links(text)
        text = re.sub(r'\[(https?://[^\s\]]+)(?:\s+([^\]]+))?\]', lambda m: self.link(m[1], m[2] or escape(m[1])), text)
        # The finite source subset uses ordinary two/three/five apostrophes.
        for marks, opening, closing in (("'''''", '<b><i>', '</i></b>'), ("'''", '<b>', '</b>'), ("''", '<i>', '</i>')):
            text = re.sub(re.escape(marks) + r'(.*?)' + re.escape(marks), lambda m: opening + m[1] + closing, text, flags=re.S)
        if re.search(r"'{2,}", re.sub(r'<[^>]*>', '', text)):
            raise RenderError('Unbalanced or unsupported apostrophe emphasis')
        return text

    def blocks(self, text):
        lines = text.splitlines()
        output, lists, wiki_table = [], [], False
        headings = Counter()

        def close_lists(level=0):
            while len(lists) > level:
                mark = lists.pop()
                output.append('</li></' + ('ol' if mark == '#' else 'ul') + '>')

        for line in lines:
            stripped = line.strip()
            if line.startswith('{|'):
                close_lists()
                if wiki_table:
                    raise RenderError('Nested wiki table unsupported')
                attrs = line[2:].strip()
                if attrs and not re.fullmatch(r'style="[^"]*"', attrs):
                    raise RenderError('Unsupported wiki-table attributes')
                output.append('<table ' + attrs + '><tr><td>'); wiki_table = True; continue
            if wiki_table and line.startswith('|}'):
                output.append('</td></tr></table>'); wiki_table = False; continue
            if wiki_table and line.startswith('|'):
                if line.startswith(('|-', '|+', '||')):
                    raise RenderError('Unsupported wiki-table row construct')
                output.append(line[1:]); continue
            heading = re.match(r'^(={2,6})(.*?)\1\s*$', line)
            if heading:
                close_lists(); level = len(heading[1]); label = heading[2].strip(); identity = anchor(plain_text(label))
                headings[identity] += 1
                if headings[identity] > 1: identity += '_' + str(headings[identity])
                output.append(f'<h{level} id="{escape(identity, quote=True)}">{label}</h{level}>'); continue
            match = re.match(r'^([*#]+)\s*(.*)$', line)
            if match:
                prefix, value = match.groups(); common = 0
                while common < min(len(lists), len(prefix)) and lists[common] == prefix[common]: common += 1
                close_lists(common)
                if len(lists) == len(prefix): output.append('</li><li>')
                else:
                    for mark in prefix[common:]:
                        output.append('<' + ('ol' if mark == '#' else 'ul') + '><li>'); lists.append(mark)
                output.append(value); continue
            if re.match(r'^[;:]', line):
                raise RenderError('Definition/indent wiki list requires explicit conversion')
            close_lists()
            if not stripped:
                output.append('<br class="paragraph-break">')
            elif re.match(r'^={1,}', line) or line.startswith(('|', '!')):
                raise RenderError('Unsupported block markup: ' + line[:80])
            else:
                output.append(line)
        close_lists()
        if wiki_table:
            raise RenderError('Unclosed wiki table')
        return '\n'.join(output)

    def render(self, title, text, display_title):
        self.current = normal_title(title); self.external = set(); self.used_images = set(); self.links = []
        text = re.sub(r'<nowiki>(.*?)</nowiki>', lambda m: escape(unescape(m[1])), text, flags=re.I | re.S)
        text = re.sub(r'</?html\s*>', '', text, flags=re.I)
        content = self.blocks(self.inline(text))
        clean = ReaderHTML(self)
        clean.feed(content); clean.close()
        result = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
                 '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'self\' \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' \
                 '<title>' + escape(display_title) + '</title><link rel="stylesheet" href="reader.css"><body>' \
                 '<nav><a href="index.html">A Book for Midwives — contents</a></nav><h1>' + display_title + '</h1><main>' + \
                 ''.join(clean.output) + '</main></body></html>'
        if len(result.encode()) > MAX_PAGE_BYTES:
            raise RenderError('Ordinary HTML page exceeds 2 MiB')
        return result, {'ids': sorted(clean.ids), 'local_links': self.links, 'external_links': sorted(self.external),
                        'images': sorted(self.used_images), 'html_tags': dict(clean.tags), 'literal_closing_braces': text.count('}}')}


class ReaderHTML(HTMLParser):
    VOID = {'area', 'br', 'col', 'hr', 'img', 'wbr'}
    ALLOWED = set('a abbr aside b blockquote br caption center code col colgroup dd details div dl dt em figure figcaption font h1 h2 h3 h4 h5 h6 hr i img li nav ol p pre section small span strong sub summary sup table tbody td th thead tr u ul wbr'.split())
    ATTRS = set('id name class style width height align valign cellpadding cellspacing border colspan rowspan scope headers title alt src href loading start value open'.split())

    def __init__(self, renderer):
        super().__init__(convert_charrefs=False)
        self.renderer = renderer; self.output = []; self.ids = set(); self.tags = Counter(); self.mapping = []

    def handle_starttag(self, tag, attrs):
        original = tag
        attrs = dict(attrs)
        # Turn publisher's JS-dependent chapter dialog into ordinary, open HTML.
        if tag == 'dialog': tag = 'aside'
        elif tag in {'button', 'form', 'select', 'option'}:
            tag = 'span'
            if original == 'select': attrs['class'] = 'publisher-mobile-selector'
        if tag not in self.ALLOWED:
            raise RenderError('Unsupported HTML element: ' + tag)
        clean = {}
        for name, value in attrs.items():
            value = value or ''
            if name.startswith('on') or name in {'data-dialog', 'method', 'selected'}:
                continue
            if name not in self.ATTRS:
                raise RenderError('Unsupported HTML attribute: ' + name)
            if name == 'style' and re.search(r'url\s*\(|expression\s*\(|@import|javascript:|behavior\s*:', value, re.I):
                raise RenderError('Unsafe or unresolved CSS dependency')
            if name == 'src' and (not value.startswith('images/') or '..' in value or not value.endswith('.png')):
                raise RenderError('Unresolved nonlocal image')
            if name == 'href':
                scheme = urlsplit(value).scheme
                if scheme and scheme not in {'http', 'https', 'mailto'}:
                    raise RenderError('Unsupported link scheme')
                if value.startswith(('http://', 'https://', 'mailto:')):
                    self.renderer.external.add(value)
                    clean['class'] = (attrs.get('class', '') + ' online').strip()
            clean[name] = value
        if tag == 'details': clean['open'] = ''
        if clean.get('id'): self.ids.add(clean['id'])
        self.tags[tag] += 1
        self.output.append('<' + tag + ''.join(' ' + k + '="' + escape(v, quote=True) + '"' for k, v in clean.items()) + '>')
        if original not in self.VOID: self.mapping.append((original, tag))

    def handle_endtag(self, tag):
        for i in range(len(self.mapping) - 1, -1, -1):
            if self.mapping[i][0] == tag:
                mapped = self.mapping[i][1]; del self.mapping[i:]
                self.output.append('</' + mapped + '>'); return
        if tag not in self.VOID:
            raise RenderError('Unmatched HTML closing tag: ' + tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID: self.handle_endtag(tag)

    def handle_data(self, data): self.output.append(data)
    def handle_entityref(self, name): self.output.append('&' + name + ';')
    def handle_charref(self, name): self.output.append('&#' + name + ';')
