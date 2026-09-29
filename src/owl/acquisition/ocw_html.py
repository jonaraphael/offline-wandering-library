"""Bounded, lossless-span localization of captured OCW HTML/CSS.

The caller verifies package/media pins and streams media separately. This module
never opens a media file or fetches a URL. Unchanged markup is copied verbatim;
its result is evidence for review, never a content-ready declaration.
"""
from __future__ import annotations

import base64
import hashlib
import posixpath
import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit

from ..safety import SafetyError

VERSION = 1
MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_CAPTION_BYTES = 4 * 1024 * 1024
MAX_ISSUES = 10000
# Exact script bodies observed in the publisher's frozen course packages. A
# modified or mixed-purpose script is retained and reported, never guessed away.
KNOWN_REPLACED_INLINE = {
    '11cfb7cba6b77be4d20bab7ac75041caa50d36679cdbf44d06e0ada971785d96': 'OCW VideoJS/YouTube bootstrap',
    '7b1b29885ad18e0ca1e2fb561060cb468648ba78999a64f44d3c5dff6c0003c3': 'OCW embedded VideoJS/YouTube bootstrap',
}
KNOWN_ANALYTICS_INLINE = {
    '916cf42ed634e73e6437b46a11e952b23e2e27457ee6f06d472063259fc561af': 'OCW Google Tag Manager bootstrap',
}
KNOWN_NAVBAR_HANDLERS = {
    "$('#mobile-course-nav-toggle').click();": 'mobile-course-nav-toggle',
    "$('#mobile-course-info-toggle').click();": 'mobile-course-info-toggle',
}
NATIVE_INFO_CLOSE = "(function(){var d=document.getElementById('course-info-drawer');d.classList.remove('in');d.style.height='';['transform','-webkit-transform','-moz-transform'].forEach(function(p){d.style.removeProperty(p)});if(!document.querySelector('.navbar-offcanvas.in'))document.body.classList.remove('offcanvas-stop-scrolling')})()"
ATTR = re.compile(r'''(?P<name>[^\s=<>/'"]+)(?:\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+)))?''')
URL_ATTRS = {'href', 'src', 'poster', 'data', 'action', 'formaction', 'data-transcriptlink'}
REMOTE = re.compile(r'''(?:https?:)?//[^\s<>"'`\\)]+''', re.I)
CSS_URL = re.compile(r'''url\(\s*(?P<quote>["']?)(?P<url>.*?)\1\s*\)|@import\s+(?P<iq>["'])(?P<import>.*?)\3''', re.I | re.S)


def _bounded(text, limit, label):
    if not isinstance(text, str) or len(text.encode('utf-8')) > limit:
        raise SafetyError(f'{label} exceeds its bounded UTF-8 text allowance')


def _portable(path):
    if not isinstance(path, str) or not path or '\\' in path or '\x00' in path or path.startswith('/') or any(p in {'', '.', '..'} for p in path.split('/')):
        raise SafetyError('OCW member and output destinations must be portable relative paths')
    return path


def _media_key(url):
    parts = urlsplit(unescape(url))
    if parts.scheme in {'http', 'https'} and parts.netloc in {'archive.org', 'www.archive.org'}:
        return parts._replace(scheme='https', netloc='archive.org').geturl()
    return url


class _Context:
    def __init__(self, member_path, output_destination, member_destinations, media_bindings, local_link_repairs=None):
        self.member = _portable(member_path)
        self.output = _portable(output_destination)
        self.members = {_portable(k): _portable(v) for k, v in member_destinations.items()}
        self.local_link_repairs = local_link_repairs or {}
        if any(not isinstance(old, str) or target not in self.members
               for old, target in self.local_link_repairs.items()):
            raise SafetyError('Explicit OCW link repair must target a pinned package member')
        self.media = {}
        for url, binding in media_bindings.items():
            key = _media_key(url)
            if key in self.media and self.media[key] != binding:
                raise SafetyError('Conflicting OCW media URL bindings')
            if not binding.get('asset_id'):
                raise SafetyError('OCW media binding requires a pinned asset identity')
            _portable(binding['destination'])
            self.media[key] = binding
        self.issues, self.external_links, self.rewrites = [], [], []
        self.navbar_dependency = None
        self.element_ids = set()
        self.elements = {}

    def issue(self, kind, value, **extra):
        row = {'kind': kind, 'value': value, **extra}
        if row not in self.issues:
            if len(self.issues) >= MAX_ISSUES:
                raise SafetyError('OCW dependency issue count exceeds bounded evidence allowance')
            self.issues.append(row)

    def relative(self, destination):
        return quote(posixpath.relpath(destination, posixpath.dirname(self.output) or '.'), safe='/.-_~')

    def url(self, value, *, active, where):
        value = unescape(value)
        if not value or value.startswith('#'):
            return value
        if _media_key(value) in self.media:
            return self.relative(self.media[_media_key(value)]['destination'])
        parts = urlsplit(value)
        if parts.scheme or parts.netloc:
            if parts.scheme == 'data' and where not in {'script.src', 'iframe.src', 'object.data', 'form.action'}:
                return value
            if active or parts.scheme.lower() in {'javascript', 'vbscript', 'file'}:
                self.issue('active-remote-dependency', value, context=where)
            elif value not in self.external_links:
                self.external_links.append(value)
            return value
        original = unquote(parts.path)
        if '\\' in original or '\x00' in original:
            self.issue('unsafe-local-link', value, context=where)
            return value
        target = posixpath.normpath(original.lstrip('/') if original.startswith('/') else posixpath.join(posixpath.dirname(self.member), original))
        if target == '..' or target.startswith('../'):
            self.issue('unsafe-local-link', value, context=where)
            return value
        candidates = [target, target.rstrip('/') + '/index.html']
        destination = next((self.members[x] for x in candidates if x in self.members), None)
        if destination is None and original.startswith('./static_resources/'):
            root_member = original[2:]
            if '..' not in root_member.split('/') and root_member in self.members:
                destination = self.members[root_member]
                self.rewrites.append({'kind':'publisher-package-root-link','original_url':value,'member':root_member})
        if destination is None and where=='css.url' and self.member.startswith('static_shared/css/') and original.startswith('images/'):
            image_member='static_shared/'+original
            if '..' not in image_member.split('/') and image_member in self.members:
                destination=self.members[image_member]
                self.rewrites.append({'kind':'publisher-shared-css-image','original_url':value,'member':image_member})
        if destination is None:
            repair = self.local_link_repairs.get(value) if where == 'a.href' else None
            if repair:
                self.rewrites.append({'kind': 'explicit-publisher-link-repair', 'original_url': value, 'member': repair})
                return self.relative(self.members[repair]) + ('?' + parts.query if parts.query else '') + ('#' + parts.fragment if parts.fragment else '')
            self.issue('unresolved-local-link', value, member=target, context=where)
            return value
        return self.relative(destination) + ('?' + parts.query if parts.query else '') + ('#' + parts.fragment if parts.fragment else '')


def _css(text, context):
    def replace(match):
        key = 'url' if match.group('url') is not None else 'import'
        value = match.group(key)
        localized = context.url(value, active=True, where='css.url')
        if localized == value:
            return match.group()
        # Keep the caller's quote style; encoded apostrophes cannot terminate it.
        localized = localized.replace("'", '%27').replace('"', '%22')
        start, end = match.span(key)
        return match.group()[:start-match.start()] + localized + match.group()[end-match.start():]
    return CSS_URL.sub(replace, text)


def localize_css(text, *, member_path, output_destination, member_destinations):
    _bounded(text, MAX_HTML_BYTES, 'OCW CSS')
    context = _Context(member_path, output_destination, member_destinations, {})
    result = _css(text, context)
    return {'css': result, 'issues': context.issues, 'rewrites':context.rewrites,
            'external_links':context.external_links, 'content_ready': False}


class _Tokens(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.lines = [0] + [m.end() for m in re.finditer('\n', text)]
        self.tokens = []
        self.feed(text)
        self.close()

    def position(self):
        line, col = self.getpos()
        return self.lines[line-1] + col

    def handle_starttag(self, tag, attrs):
        start = self.position()
        self.tokens.append({'kind':'start', 'tag':tag, 'attrs':dict(attrs), 'start':start, 'end':start+len(self.get_starttag_text()), 'raw':self.get_starttag_text()})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.tokens[-1]['self_closing'] = True

    def handle_endtag(self, tag):
        start = self.position()
        end = self.text.find('>', start)
        if end < 0:
            raise SafetyError('Truncated OCW end tag')
        self.tokens.append({'kind':'end', 'tag':tag, 'start':start, 'end':end+1})


def _apply(text, edits):
    cursor, result = 0, []
    for start, end, replacement in sorted(edits):
        if start < cursor:
            raise SafetyError('Overlapping OCW markup rewrites')
        result.extend((text[cursor:start], replacement))
        cursor = end
    result.append(text[cursor:])
    return ''.join(result)


def _tag(token, context, overrides=None, remove=()):
    raw, edits, found = token['raw'], [], set()
    overrides = overrides or {}
    tag_end = re.match(r'<\s*[^\s/>]+', raw).end()
    for match in ATTR.finditer(raw, tag_end):
        name = match.group('name').lower()
        if name in found:
            context.issue('duplicate-html-attribute', name, context=token['tag'])
            continue
        found.add(name)
        if name in remove:
            edits.append((*match.span(), ''))
            continue
        key = next((key for key in ('double','single','bare') if match.group(key) is not None), None)
        if name in overrides:
            value = overrides[name]
        elif key and name in URL_ATTRS:
            active = not (name == 'href' and (token['tag'] == 'a' or (token['tag'] == 'link' and token['attrs'].get('rel') in {'canonical','alternate','license'})))
            value = context.url(match.group(key), active=active, where=token['tag']+'.'+name)
        elif key and name == 'style':
            value = _css(unescape(match.group(key)), context)
        elif key and name == 'srcset':
            context.issue('unsupported-srcset', unescape(match.group(key)), context=token['tag'])
            continue
        elif name.startswith('on'):
            value = unescape(match.group(key)) if key else ''
            drawer=context.elements.get('course-info-drawer',{})
            if (name=='onclick' and value=="$('#mobile-course-info-toggle').click();"
                    and context.member=='index.html' and context.navbar_dependency
                    and 'mobile-course-info-toggle' not in context.element_ids
                    and token['tag']=='button' and token['attrs'].get('id')=='close-mobile-course-info-button'
                    and token['attrs'].get('type')=='button' and token['attrs'].get('aria-label')=='Close Course Info'
                    and {'btn','close-mobile-course-info'}<=set(token['attrs'].get('class','').split())
                    and {'navbar-offcanvas','navbar-offcanvas-right','medium-and-below-only'}<=set(drawer.get('class','').split())):
                edits.append((*match.span(),'onclick="'+escape(NATIVE_INFO_CLOSE,quote=True)+'"'))
                context.rewrites.append({'kind':'repair-missing-homepage-info-toggle',
                    'original_tag_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                    'target':'course-info-drawer','target_classes':drawer['class'],
                    'dependency_member':context.navbar_dependency,
                    'required_review':'Offline responsive drawer closing, body scroll and local navigation behavior'})
                continue
            if (name=='onclick' and value in KNOWN_NAVBAR_HANDLERS and context.navbar_dependency
                    and KNOWN_NAVBAR_HANDLERS[value] in context.element_ids):
                context.rewrites.append({'kind':'retained-reviewed-navbar-handler','value':value,'dependency_member':context.navbar_dependency})
            else:
                context.issue('retained-event-handler',value,context=token['tag'],attribute=name)
            continue
        else:
            continue
        if key is None or value != unescape(match.group(key)):
            edits.append((*match.span(), name+'="'+escape(value, quote=True)+'"'))
    extra = ''.join(' '+name+'="'+escape(value, quote=True)+'"' for name,value in overrides.items() if name not in found)
    if extra:
        index = len(raw.rstrip()) - (2 if raw.rstrip().endswith('/>') else 1)
        edits.append((index,index,extra))
    return _apply(raw, edits)


def _native(token, inner, binding, context, caption_texts):
    captions = binding.get('captions', [])
    variants = binding.get('caption_variants')
    if variants:
        if not isinstance(variants,list) or len(variants)>128:
            raise SafetyError('OCW caption variants exceed their finite bound')
        original_members=[]
        for row in _Tokens(inner).tokens:
            if row['kind']!='start' or row['tag']!='track' or row['attrs'].get('srclang') not in {'en','en-US','en-GB'}:
                continue
            source=urlsplit(row['attrs'].get('src',''))
            if source.scheme or source.netloc or not source.path:
                continue
            original=unquote(source.path)
            member=posixpath.normpath(original.lstrip('/') if original.startswith('/') else posixpath.join(posixpath.dirname(context.member),original))
            if member not in context.members and original.startswith('./static_resources/'):
                member=original[2:]
            if member in context.members:
                original_members.append(member)
        matches=[]
        pins=binding.get('caption_member_sha256',{})
        for variant in variants:
            candidate=variant.get('captions',[])
            accepted_members={name for c in candidate for name in [c['member_path'],*c.get('member_aliases',[])]}
            exact=bool(original_members) and set(original_members)<=accepted_members
            hashes={c.get('sha256') for c in candidate if c.get('sha256')}
            by_hash=bool(original_members) and bool(hashes) and all(pins.get(member) in hashes for member in original_members)
            if exact or by_hash:
                matches.append(candidate)
        if len(matches)!=1:
            context.issue('ambiguous-caption-variant' if matches else 'unresolved-caption-variant',
                token['attrs'].get('data-downloadlink',''), original_track_members=original_members)
            return None
        captions=matches[0]
        context.rewrites.append({'kind':'caption-variant','original_track_members':original_members,'selected_caption_members':[c['member_path'] for c in captions]})
    if not captions or len(captions) > 128 or not any(c.get('language') == 'en' for c in captions):
        context.issue('missing-English-captions', token['attrs'].get('data-downloadlink',''))
        return None
    tracks, transcripts, total_caption_bytes = [], [], 0
    for caption in captions:
        member, language = caption.get('member_path'), caption.get('language')
        if member not in context.members or member not in caption_texts or not language:
            context.issue('missing-caption-member', str(member))
            return None
        text = caption_texts[member]
        _bounded(text, MAX_CAPTION_BYTES, 'OCW caption')
        total_caption_bytes += len(text.encode('utf-8'))
        if total_caption_bytes > MAX_CAPTION_BYTES:
            raise SafetyError('Combined OCW video captions exceed 4 MiB')
        if not text.lstrip('\ufeff').startswith('WEBVTT') or '-->' not in text:
            context.issue('invalid-WebVTT-caption', member)
            return None
        label = caption.get('label') or language
        encoded = base64.b64encode(text.lstrip('\ufeff').encode()).decode('ascii')
        tracks.append('<track kind="captions" src="data:text/vtt;base64,'+encoded+'" srclang="'+escape(language,quote=True)+'" label="'+escape(label,quote=True)+'"'+(' default' if language=='en' else '')+'>')
        transcripts.append('<details><summary>'+escape(label)+' timed transcript</summary><p><a href="'+escape(context.relative(context.members[member]),quote=True)+'">Original WebVTT caption file</a></p><pre>'+escape(text)+'</pre></details>')
    media = context.relative(binding['destination'])
    timing = []
    for name in ('start_time','end_time'):
        value = binding.get(name)
        if value not in (None, ''):
            normalized = str(value).strip()
            if not re.fullmatch(r'\d+(?:\.\d+)?',normalized):
                context.issue('unsupported-media-timing', str(value), field=name)
                return None
            timing.append(normalized)
        elif name == 'start_time' and binding.get('end_time') not in (None,''):
            timing.append('0')
    if len(timing)==2 and float(timing[1]) <= float(timing[0]):
        context.issue('invalid-media-timing', ','.join(timing))
        return None
    media_timed = media + ('#t='+','.join(timing) if timing else '')
    classes = ' '.join(x for x in token['attrs'].get('class','').split() if x != 'video-js' and not x.startswith('vjs-'))
    opening = _tag(token, context, {'controls':'', 'preload':'metadata', 'class':classes, 'data-downloadlink':media}, remove=('data-setup',))
    preserved = re.sub(r'<(?:track|source)\b[^>]*>', '', inner, flags=re.I)
    fallback = localize_html(preserved, member_path=context.member,
        output_destination=context.output, member_destinations=context.members,
        media_bindings={}, caption_texts={})
    preserved = fallback['html']
    for issue in fallback['issues']:
        context.issue(issue['kind'], issue['value'], **{k:v for k,v in issue.items() if k not in {'kind','value'}})
    context.external_links.extend(url for url in fallback['external_links'] if url not in context.external_links)
    native = opening+'<source src="'+escape(media_timed,quote=True)+'" type="'+escape(binding.get('mime_type','video/mp4'),quote=True)+'">'+''.join(tracks)+preserved+'<p><a href="'+escape(media_timed,quote=True)+'">Open the original media file</a></p></video>'+''.join(transcripts)
    context.rewrites.append({'kind':'native-video','asset_id':binding['asset_id'],'captions':[c['member_path'] for c in captions], 'start_time':binding.get('start_time'), 'end_time':binding.get('end_time')})
    return native


def localize_html(text, *, member_path, output_destination, member_destinations, media_bindings, caption_texts, local_link_repairs=None, reviewed_omissions=()):
    _bounded(text, MAX_HTML_BYTES, 'OCW HTML')
    context = _Context(member_path, output_destination, member_destinations, media_bindings, local_link_repairs)
    tokens, edits, covered, generated_bytes = _Tokens(text).tokens, [], [], 0
    omissions, applied = {}, {}
    if not isinstance(reviewed_omissions, (list, tuple)) or len(reviewed_omissions)>1000:
        raise SafetyError('OCW reviewed omissions must be a bounded exact tag list')
    for row in reviewed_omissions:
        key=row.get('tag_sha256')
        if (not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key) or key in omissions
                or row.get('kind') not in {'decorative-image','obsolete-external-warning-handler'}
                or not isinstance(row.get('reason'),str) or not 1<=len(row['reason'])<=1000
                or type(row.get('count')) is not int or not 1<=row['count']<=100):
            raise SafetyError('OCW omission needs an exact tag pin, finite count and reviewed reason')
        omissions[key]=row;applied[key]=0
    context.element_ids = {row['attrs']['id'] for row in tokens if row['kind']=='start' and row['attrs'].get('id')}
    context.elements = {row['attrs']['id']:row['attrs'] for row in tokens if row['kind']=='start' and row['attrs'].get('id')}
    for token in tokens:
        if token['kind']=='start' and token['tag']=='script' and token['attrs'].get('src'):
            src = urlsplit(token['attrs']['src'])
            if not src.scheme and not src.netloc:
                member = posixpath.normpath(posixpath.join(posixpath.dirname(context.member),unquote(src.path)))
                if re.fullmatch(r'static_shared/js/course_offline\.[a-zA-Z0-9]+\.js',member) and member in context.members:
                    context.navbar_dependency = member
    # Replace complete video spans first so bootstrap deletion requires actual
    # local native media and complete caption success, not merely a proposed pin.
    for index, token in enumerate(tokens):
        if token['kind'] != 'start' or token['tag'] != 'video':
            continue
        end = next((row for row in tokens[index+1:] if row['tag']=='video'), None)
        if end is None or end['kind'] != 'end':
            context.issue('malformed-video', str(token['start']))
            continue
        url = token['attrs'].get('data-downloadlink','')
        binding = context.media.get(_media_key(url))
        if binding is None:
            context.issue('unpinned-video', url)
            continue
        native = _native(token, text[token['end']:end['start']], binding, context, caption_texts)
        if native is not None:
            generated_bytes += len(native.encode('utf-8'))
            if generated_bytes > MAX_HTML_BYTES + 3*MAX_CAPTION_BYTES:
                raise SafetyError('Combined native OCW video markup exceeds output allowance')
            edits.append((token['start'],end['end'],native))
            covered.append((token['start'],end['end']))
    replaced = bool(covered) and len(covered) == sum(row['kind']=='start' and row['tag']=='video' for row in tokens)
    for index, token in enumerate(tokens):
        if token['kind'] != 'start' or any(a<=token['start']<b for a,b in covered):
            continue
        tag_pin=hashlib.sha256(token['raw'].encode()).hexdigest()
        omission=omissions.get(tag_pin)
        if omission:
            attrs=token['attrs']
            if omission['kind']=='decorative-image':
                if token['tag']!='img' or attrs.get('alt')!='' or any(attrs.get(k) for k in ['longdesc','usemap','title']):
                    raise SafetyError('Reviewed decorative omission cannot remove labelled image content')
                replacement='<span class="owl-omitted-decoration" aria-hidden="true"></span>'
            else:
                if (token['tag']!='a' or attrs.get('onclick')!='event.preventDefault()'
                        or 'external-link-warning' not in attrs.get('class','').split()
                        or urlsplit(attrs.get('href','')).scheme!='https'):
                    raise SafetyError('Reviewed warning repair differs from original optional external anchor')
                replacement=_tag(token,context,remove=('onclick',))
            edits.append((token['start'],token['end'],replacement));applied[tag_pin]+=1
            context.rewrites.append({'kind':'explicit-reviewed-omission',**omission})
            continue
        if token['tag']=='iframe' and token['attrs'].get('src')=='https://www.googletagmanager.com/ns.html?id=GTM-NMQZ25T':
            end = next((row for row in tokens[index+1:] if row['tag']=='iframe'),None)
            if end and end['kind']=='end' and not text[token['end']:end['start']].strip():
                edits.append((token['start'],end['end'],''))
                context.rewrites.append({'kind':'removed-runtime','reason':'OCW Google Tag Manager noscript frame','source_url':token['attrs']['src']})
                continue
        if token['tag'] in {'script','style'}:
            end = next((row for row in tokens[index+1:] if row['kind']=='end' and row['tag']==token['tag']), None)
            if end is None:
                context.issue('unterminated-runtime', token['tag'])
                continue
            body = text[token['end']:end['start']]
            if token['tag']=='style':
                localized = _css(body,context)
                if localized != body:
                    edits.append((token['end'],end['start'],localized))
            elif token['attrs'].get('type','').lower() not in {'application/ld+json','application/json'}:
                digest = hashlib.sha256(body.encode()).hexdigest()
                if digest in KNOWN_ANALYTICS_INLINE or replaced and digest in KNOWN_REPLACED_INLINE:
                    edits.append((token['start'],end['end'],''))
                    context.rewrites.append({'kind':'removed-runtime','sha256':digest,'reason':KNOWN_ANALYTICS_INLINE.get(digest) or KNOWN_REPLACED_INLINE[digest]})
                    continue
                for url in REMOTE.findall(body):
                    context.issue('active-remote-dependency', url, context='inline-script', sha256=digest)
                if any(key in body for key in ('initVideoJS','handleVideoJSError','youtube.com/iframe_api','googletagmanager')):
                    context.issue('unreviewed-player-runtime', digest)
        if token['tag'] in {'iframe','object','embed','base'}:
            context.issue('retained-essential-dependency', token['tag'], context=str(token['start']))
        rewritten = _tag(token,context)
        if rewritten != token['raw']:
            edits.append((token['start'],token['end'],rewritten))
    if any(applied[key]!=row['count'] for key,row in omissions.items()):
        raise SafetyError('Reviewed OCW omission count differs from exact pinned source tags')
    result = _apply(text,edits)
    # Output includes original complete transcripts plus embedded VTT tracks.
    _bounded(result, MAX_HTML_BYTES + 3*MAX_CAPTION_BYTES, 'Localized OCW HTML')
    return {'html':result,'issues':context.issues,'rewrites':context.rewrites,'external_links':context.external_links,'content_ready':False}
