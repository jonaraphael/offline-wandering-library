"""Exact source-bound repairs for Python documentation opened as ordinary files."""
import hashlib
import json
from ..safety import SafetyError

RUNTIME_MEMBERS = {
    'python-glossary-file-v1': '/_static/glossary_search.js',
    'python-title-search-file-v1': '/_static/searchtools.js',
    'python-feedback-defaults-v1': '/improve-page.html',
}
GLOSSARY_FETCH = '''  const response = await fetch("_static/glossary.json");
  if (!response.ok) {
    throw new Error("Failed to fetch glossary.json");
  }
  const glossary = await response.json();'''
SEARCH_SUMMARY = 'const showSearchSummary = DOCUMENTATION_OPTIONS.SHOW_SEARCH_SUMMARY;'
FEEDBACK_PARAMS = 'const params = new URLSearchParams(window.location.search);'


def validate_runtime(member):
    patch=member.get('runtime_patch')
    if patch is not None and (not isinstance(patch,str) or patch not in RUNTIME_MEMBERS or not member['path'].endswith(RUNTIME_MEMBERS[patch])):
        raise SafetyError('Unknown or misplaced Python manual runtime repair')


def auxiliary(archive, members):
    """Read the exact glossary member named by the complete source manifest."""
    selected=[m for m in members if m.get('runtime_patch')=='python-glossary-file-v1']
    if not selected:return {}
    if len(selected)!=1:raise SafetyError('Python glossary patch must have exactly one runtime member')
    path=selected[0]['path'].rsplit('/',1)[0]+'/glossary.json'
    found=[m for m in members if m['path']==path]
    if len(found)!=1 or not 0<found[0]['size_bytes']<=1024*1024:raise SafetyError('Missing or excessive pinned Python glossary data')
    member=found[0]
    with archive.archive.open(path) as stream:data=stream.read(member['size_bytes']+1)
    if len(data)!=member['size_bytes'] or hashlib.sha256(data).hexdigest()!=member['sha256']:
        raise SafetyError('Python glossary input differs from its complete member pin')
    return {path:data}


def repair(data,member,inputs):
    validate_runtime(member);patch=member.get('runtime_patch')
    if patch is None:return data
    text=data.decode('utf-8')
    if patch=='python-glossary-file-v1':
        path=member['path'].rsplit('/',1)[0]+'/glossary.json'
        if path not in inputs:raise SafetyError('Python file glossary needs its pinned auxiliary member')
        glossary=json.loads(inputs[path])
        if not isinstance(glossary,dict) or not 1<=len(glossary)<=10000:raise SafetyError('Unexpected Python glossary structure')
        before=GLOSSARY_FETCH
        after='  // OWL: complete pinned glossary embedded for ordinary-file access.\n  const glossary = '+json.dumps(glossary,ensure_ascii=True,separators=(',',':'))+';'
    elif patch=='python-title-search-file-v1':
        before=SEARCH_SUMMARY
        after='''const showSearchSummary = DOCUMENTATION_OPTIONS.SHOW_SEARCH_SUMMARY && location.protocol !== "file:";
  if (location.protocol === "file:" && !document.getElementById("owl-file-search-note")) {
    const note = document.createElement("p");
    note.id = "owl-file-search-note";
    note.textContent = "Matching page titles are shown below. Open a result to read the complete documentation.";
    document.getElementById("search-results").prepend(note);
  }'''
    else:
        before=FEEDBACK_PARAMS
        after=FEEDBACK_PARAMS+'''
      if (!params.get('pagetitle')) params.set('pagetitle', 'Python documentation index');
      if (!params.get('pageurl')) params.set('pageurl', new URL('index.html', window.location.href).href);
      if (!params.get('pagesource')) params.set('pagesource', 'index.rst');'''
    if text.count(before)!=1:raise SafetyError('Python runtime repair source span changed')
    return text.replace(before,after).encode('utf-8')
