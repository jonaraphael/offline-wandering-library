"""Local classic-script transport preserves the binary search engine without a picker."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from owl.search import build_search

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src/owl/templates/search.js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is required for the browser transport tests")
class ScriptSearchTransportTests(unittest.TestCase):
    def js(self, body):
        prefix = "const assert=require('node:assert/strict'); const fs=require('node:fs');\n"
        prefix += "const engine=require(" + json.dumps(str(RUNTIME)) + ");\n"
        prefix += "const C=1048576, hash='a'.repeat(64); const manifest=size=>({version:1,index_sha256:hash,size,chunk_bytes:C,chunk_count:Math.ceil(size/C)});\n"
        script = prefix + "(async()=>{\n" + body + "\n})().catch(error=>{console.error(error);process.exitCode=1});\n"
        result = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                                encoding="utf-8", timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_manifest_rejects_urls_bad_counts_and_noninteger_offsets(self):
        self.js("""
const good=manifest(C+17); assert.deepEqual(engine.validateManifest(good),good);
assert.ok(Object.isFrozen(engine.validateManifest(good)));
for(const value of [null,[],{...good,version:2},{...good,size:4095},{...good,size:Infinity},
  {...good,size:4096.1},{...good,chunk_bytes:C*2},{...good,chunk_count:3},
  {...good,chunk_count:1.5},{...good,index_sha256:'A'.repeat(64)},
  {...good,index_sha256:'../evil'},{...good,url:'https://example.invalid/index.js'},
  {...good,size:C*100000001,chunk_count:100000001}]) assert.throws(()=>engine.validateManifest(value));
const file=new engine.ScriptChunkFile(good,()=>{throw Error('No reads expected')});
for(const bounds of [[-1,1],[0,NaN],[0,1.5],[2,1],[0,C+1],[C,C+18]]) assert.throws(()=>file.slice(...bounds));
assert.equal((await file.slice(0,0).arrayBuffer()).byteLength,0);
""")

    def test_cross_boundary_slices_short_last_chunk_and_fixed_paths(self):
        self.js(r"""
const m=manifest(C*2+17), paths=[];
const load=async(url,callback,receive)=>{
 paths.push(url);assert.equal(callback,'OWLSearchChunk');
 const id=Number(url.match(/\/(\d{8})\.js$/)[1]);
 assert.equal(url,`SEARCH/chunks/${hash}/${String(id).padStart(8,'0')}.js`);
 return receive(hash,id,Buffer.alloc(Math.min(C,m.size-id*C),id).toString('base64'));
};
const file=new engine.ScriptChunkFile(m,load);
assert.deepEqual([...new Uint8Array(await file.slice(C-3,C+4).arrayBuffer())],[0,0,0,1,1,1,1]);
assert.deepEqual([...new Uint8Array(await file.slice(C*2+14,C*2+17).arrayBuffer())],[2,2,2]);
assert.equal(paths.length,3);assert.equal(file.pending.size,0);
""")

    def test_concurrent_requests_are_deduplicated_serialized_and_lru_bounded(self):
        self.js(r"""
const m=manifest(C*10), seen=[], active={now:0,max:0};
const load=async(url,callback,receive)=>{
 const id=Number(url.match(/\/(\d{8})\.js$/)[1]);seen.push(id);active.now++;active.max=Math.max(active.max,active.now);
 await new Promise(resolve=>setTimeout(resolve,1));
 const result=receive(hash,id,Buffer.alloc(C,id).toString('base64'));active.now--;return result;
};
const file=new engine.ScriptChunkFile(m,load);
const first=await Promise.all(Array.from({length:20},()=>file.slice(0,1).arrayBuffer()));
assert.ok(first.every(value=>new Uint8Array(value)[0]===0));assert.deepEqual(seen,[0]);
await Promise.all(Array.from({length:9},(_,i)=>file.slice((i+1)*C,(i+1)*C+1).arrayBuffer()));
assert.equal(active.max,1);assert.equal(file.cache.size,8);assert.equal(file.pending.size,0);
assert.deepEqual([...file.cache.keys()],[2,3,4,5,6,7,8,9]);
await file.slice(2*C,2*C+1).arrayBuffer();await file.slice(0,1).arrayBuffer();
assert.equal(file.cache.size,8);assert.equal(file.cache.has(2),true);assert.equal(file.cache.has(3),false);
assert.equal(seen.filter(id=>id===0).length,2);
""")

    def test_bad_chunk_identity_base64_and_failed_load_can_retry(self):
        self.js("""
const m=manifest(C+1), valid=Buffer.from([7]).toString('base64');
for(const values of [['b'.repeat(64),1,valid],[hash,0,valid],[hash,1,'AA==junk'],
 [hash,1,'AB=='],[hash,1,'AA=A'],[hash,1,' AA=='],[hash,1,'AAA=']]){
 const file=new engine.ScriptChunkFile(m,async(url,name,receive)=>receive(...values));
 await assert.rejects(file.slice(C,C+1).arrayBuffer());assert.equal(file.cache.size,0);assert.equal(file.pending.size,0);
}
let calls=0;const file=new engine.ScriptChunkFile(m,async(url,name,receive)=>{
 if(++calls===1)throw Error('missing chunk');return receive(hash,1,valid);
});
await assert.rejects(file.slice(C,C+1).arrayBuffer(),/missing chunk/);
assert.equal(new Uint8Array(await file.slice(C,C+1).arrayBuffer())[0],7);assert.equal(calls,2);
""")

    def test_classic_script_callbacks_remove_elements_timers_and_allow_retry(self):
        self.js("""
const vm=require('node:vm');const code=fs.readFileSync(""" + json.dumps(str(RUNTIME)) + """,'utf8');
const scripts=new Set(), timers=new Map();let nextTimer=0, action=null, created=0;
const sandbox={module:{exports:{}},TextEncoder,TextDecoder,atob,
 setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},
 document:{getElementById(){return null;},createElement(tag){assert.equal(tag,'script');created++;
  return {remove(){scripts.delete(this);}};},head:{append(script){scripts.add(script);if(action)action(script);}}}};
vm.runInNewContext(code,sandbox);const api=sandbox.module.exports;
assert.equal(timers.size,0);assert.equal(created,0);
const m=manifest(4096);
action=script=>{assert.equal(script.src,'SEARCH/manifest.js');assert.equal(script.type,undefined);assert.equal(script.crossOrigin,undefined);
 sandbox.OWLSearchManifest(m);script.onload();};
assert.equal((await api.loadManifest()).size,4096);assert.equal(scripts.size,0);assert.equal(timers.size,0);
assert.equal('OWLSearchManifest' in sandbox,false);
action=script=>script.onload();await assert.rejects(api.loadManifest(),/returned no data/);
action=script=>{sandbox.OWLSearchManifest(m);sandbox.OWLSearchManifest(m);};
await assert.rejects(api.loadManifest(),/duplicate data/);
action=script=>script.onerror();await assert.rejects(api.loadManifest(),/could not be loaded/);
action=null;const timed=api.loadManifest();const failed=assert.rejects(timed,/timed out/);
for(let i=0;i<10 && timers.size===0;i++)await Promise.resolve();assert.equal(timers.size,1);
[...timers.values()][0]();await failed;assert.equal(scripts.size,0);assert.equal(timers.size,0);
action=script=>{sandbox.OWLSearchManifest(m);script.onload();};await api.loadManifest();
assert.equal(scripts.size,0);assert.equal(timers.size,0);assert.equal('OWLSearchManifest' in sandbox,false);
""")

    def test_actual_binary_index_search_works_through_script_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve()
            assets = []
            for name, text, kind, illustrated in [
                ("manual.txt", "Repair a water pump. The impeller moves water.", "guide", True),
                ("lesson.txt", "Biology textbook: photosynthesis uses light.", "textbook", True),
            ]:
                (target / name).write_text(text, encoding="utf-8")
                assets.append(dict(id=name.split(".")[0], title=name, destination=name, format="txt",
                                   category="reference", resource_type=kind, illustrated=illustrated,
                                   reader_required=False))
            report = build_search(target, assets)
            self.js("""
const root=""" + json.dumps(str(target)) + """;
const encodedManifest=fs.readFileSync(root+'/SEARCH/manifest.js','utf8');
const m=JSON.parse(encodedManifest.slice('globalThis.OWLSearchManifest('.length,-3));
assert.equal(m.index_sha256,""" + json.dumps(report["index_sha256"]) + """);
let reads=0;const load=async(url,name,receive)=>{reads++;
 const script=fs.readFileSync(root+'/'+url,'utf8');
 const args=JSON.parse('['+script.slice('globalThis.OWLSearchChunk('.length,-3)+']');
 return receive(...args);};
const index=new engine.Index(new engine.ScriptChunkFile(m,load));await index.open();
const water=await index.search('impeller');assert.equal(water.results[0].destination,'manual.txt');
const textbook=await index.search('photosynthesis',{shelf:'textbooks'});assert.equal(textbook.results[0].destination,'lesson.txt');
assert.equal((await index.search('photosynthesis',{shelf:'illustrated-guides'})).results.length,1);
assert.equal(engine.safeLink(textbook.results[0]),'lesson.txt');assert.equal(reads,1);
""")


if __name__ == "__main__":
    unittest.main()
