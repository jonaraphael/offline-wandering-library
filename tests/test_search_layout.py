"""Both search entry points resolve only into the single LIBRARY folder."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from owl.search_ui import render_search_page, render_search_widget


class _Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.scripts, self.forms = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "script":
            self.scripts.append(attrs)
        if tag == "form":
            self.forms.append(attrs)


class SearchLayoutTests(unittest.TestCase):
    def test_widget_has_explicit_prefix_and_standalone_returns_to_outer_start(self):
        outer = _Links(render_search_widget("LIBRARY/"))
        self.assertTrue(all(link.startswith("LIBRARY/") for link in outer.links))
        self.assertEqual(outer.scripts, [{"defer": None, "src": "LIBRARY/SEARCH/search.js"}])
        self.assertEqual(outer.forms[0]["data-library-root"], "LIBRARY/")
        page = render_search_page()
        inner = _Links(page)
        self.assertIn("../START_HERE.html", inner.links)
        self.assertIn("INDEX/categories.html", inner.links)
        self.assertEqual(inner.forms[0]["data-library-root"], "")
        self.assertEqual(inner.scripts, [{"defer": None, "src": "SEARCH/search.js"}])
        self.assertNotIn("__OWL_", page)
        self.assertNotIn("<base", page)
        self.assertNotIn('type="file"', page)

    def test_widget_rejects_arbitrary_locations(self):
        for prefix in ("../", "/LIBRARY/", "https://example.invalid/", "LIBRARY//", "other/"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                render_search_widget(prefix)

    @unittest.skipUnless(shutil.which("node"), "Node checks search runtime URL resolution")
    def test_runtime_prefixes_manifest_chunks_results_and_rejects_unsafe_roots(self):
        runtime = Path(__file__).resolve().parents[1] / "src/owl/templates/search.js"
        script = "const engine=require(" + json.dumps(str(runtime)) + ");\n" + r"""
const assert=require('node:assert/strict');
(async()=>{
 const hash='a'.repeat(64), m={version:1,index_sha256:hash,size:4096,chunk_bytes:1048576,chunk_count:1};
 for(const prefix of ['', 'LIBRARY/']) {
   let manifestPath, chunkPath;
   const loaded=await engine.loadManifest(async(path,name,receive)=>{
     manifestPath=path;assert.equal(name,'OWLSearchManifest');return receive(m);
   },prefix);
   assert.equal(manifestPath,prefix+'SEARCH/manifest.js');
   const file=new engine.ScriptChunkFile(loaded,async(path,name,receive)=>{
     chunkPath=path;assert.equal(name,'OWLSearchChunk');return receive(hash,0,Buffer.alloc(4096,7).toString('base64'));
   },prefix);
   assert.equal(new Uint8Array(await file.slice(0,1).arrayBuffer())[0],7);
   assert.equal(chunkPath,prefix+'SEARCH/chunks/'+hash+'/00000000.js');
   assert.equal(engine.safeLink({destination:'BOOKS/a #b.pdf',format:'pdf',page:3},prefix),prefix+'BOOKS/a%20%23b.pdf#page=3');
   assert.equal(engine.safeLink({destination:'../escape.html'},prefix),null);
 }
 for(const prefix of ['../','/LIBRARY/','https://example.invalid/','LIBRARY//','other/']) {
   await assert.rejects(engine.loadManifest(()=>{throw Error('unexpected load')},prefix),/Invalid local library/);
   assert.throws(()=>new engine.ScriptChunkFile(m,()=>{},prefix),/Invalid local library/);
   assert.throws(()=>engine.safeLink({destination:'BOOKS/safe.pdf'},prefix),/Invalid local library/);
 }
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
