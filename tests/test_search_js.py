"""Compact browser decoding must reject corrupt input before ranking it."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


RUNTIME = Path(__file__).resolve().parents[1] / "src/owl/templates/search.js"
NODE = shutil.which("node")

FIXTURE = r"""
const assert = require('node:assert/strict'), zlib = require('node:zlib');
function varint(value) {
 const bytes=[];
 do { const digit=value%128;value=Math.floor(value/128);bytes.push(digit|(value?128:0)); } while(value);
 return bytes;
}
function fixture(options={}) {
 const count=options.documents??3, postingCount=options.postingCount??count;
 const record=options.record??{title:'Water reference',text:'Water sanitation and shelter.',destination:'REFERENCE/water.txt',format:'txt'};
 const compressed=options.compressed??zlib.deflateSync(Buffer.from(JSON.stringify(record)));
 const prefix=Buffer.alloc(4096), docsOffset=4096+compressed.length;
 const table=Buffer.alloc(count*12);
 for(let id=0;id<count;id++){table.writeBigUInt64LE(4096n,id*12);table.writeUInt32LE(compressed.length,id*12+8);}
 const flags=Buffer.alloc(count,options.flags??3), flagsOffset=docsOffset+table.length;
 const postings=Buffer.from(options.postings??Array.from({length:count},(_,i)=>[...varint(i?1:0),1,1]).flat());
 const postingOffset=flagsOffset+flags.length;
 const term=Buffer.from(JSON.stringify(options.term??['water',postingOffset,postingCount,postings.length]));
 const lexiconOffset=postingOffset+postings.length+term.length;
 const lexicon=Buffer.alloc(12);lexicon.writeBigUInt64LE(BigInt(postingOffset+postings.length));lexicon.writeUInt32LE(term.length,8);
 const header={version:3,document_encoding:'zlib-json-v1',postings_encoding:'delta-uvarint-v1',
  tokenizer:'NFKC-lower-unicode-letter-number-v1',documents:count,terms:1,average_length:1,
  docs_offset:docsOffset,flags_offset:flagsOffset,lexicon_offset:lexiconOffset,size:lexiconOffset+12,...options.header};
 const encoded=Buffer.from(JSON.stringify(header));prefix.write(options.magic??'OWLIDX3\n');prefix.writeUInt32LE(encoded.length,8);encoded.copy(prefix,12);
 const data=Buffer.concat([prefix,compressed,table,flags,postings,term,lexicon]);
 return {data,header,postingOffset,postingEnd:postingOffset+postings.length};
}
function openFixture(value,reads=[]) {
 const blob=new Blob([value.data]);
 const file={size:blob.size,slice(start,end){reads.push([start,end-start]);return blob.slice(start,end);}};
 return new engine.Index(file);
}
"""


@unittest.skipUnless(NODE, "Node is required for native browser decoder tests")
class CompactSearchDecoderTests(unittest.TestCase):
    def js(self, body):
        script = "const engine=require(" + json.dumps(str(RUNTIME)) + ");\n" + FIXTURE
        script += "\n(async()=>{\n" + body + "\n})().catch(error=>{console.error(error);process.exitCode=1});"
        result = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                                encoding="utf-8", timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_compressed_unicode_records_max_uint32_and_document_zero(self):
        self.js(r"""
const value=fixture({documents:1,postings:[0,...varint(4294967295),...varint(4294967295)],
 record:{title:'Eau et électricité',text:'Water — 安全',destination:'REFERENCE/eau.txt',format:'txt',
 attribution:'Access for free at openstax.org.',license:'CC-BY-NC-SA-4.0'}});
const index=openFixture(value);await index.open();
const result=await index.search('water',{shelf:'textbooks'});
assert.equal(result.results[0].id,0);assert.equal(result.results[0].title,'Eau et électricité');
assert.equal(result.results[0].attribution,'Access for free at openstax.org.');
assert.equal(result.results[0].text,'Water — 安全');assert.ok(Number.isFinite(result.results[0].score));
assert.equal((await index.search('water',{shelf:'illustrated-guides'})).matches,1);
""")

    def test_byte_windows_handle_split_varints_without_large_posting_reads(self):
        self.js(r"""
const count=25000, postings=[];
for(let id=0;id<count;id++)postings.push(...varint(id?1:0),...varint(id%2?256:1),...varint(16384));
const value=fixture({documents:count,postings}), reads=[], index=openFixture(value,reads);
await index.open();const result=await index.search('water',{limit:1});
assert.equal(result.matches,count);assert.equal(result.results[0].id,1);
const postingReads=reads.filter(([at])=>at>=value.postingOffset&&at<value.postingEnd);
assert.ok(postingReads.length>2);assert.ok(postingReads.every(([,length])=>length<=48*1024));
assert.ok(reads.every(([,length])=>length<=1048576));
""")

    def test_varint_corruption_and_posting_bounds_are_rejected(self):
        self.js(r"""
const cases=[
 [[0,1,128],1,/Truncated/],
 [[0,128,1],1,/Truncated/],
 [[128,0,1,1],1,/Overlong/],
 [[128,128,128,128,128,0,1,1],1,/overflow|overlong/i],
 [[255,255,255,255,16,1,1],1,/overflow/i],
 [[0,0,1],1,/Invalid posting/],
 [[0,1,0],1,/Invalid posting/],
 [[0,1,1,0,1,1],2,/Invalid posting/],
 [[0,1,1,3,1,1],2,/Invalid posting/],
 [[0,1,1,0],1,/Trailing/]
];
for(const [postings,postingCount,message]of cases){const index=openFixture(fixture({postings,postingCount}));await index.open();await assert.rejects(index.search('water'),message);}
for(const term of [['water',0,1,3],['water',5000,1,2],['water',5000,1,16],['water',5000,0,0],['water',5000,1]]){
 const index=openFixture(fixture({term}));await index.open();await assert.rejects(index.search('water'),/Invalid/);
}
""")

    def test_compression_checksum_truncation_trailing_data_and_record_limits(self):
        self.js(r"""
const valid=zlib.deflateSync(Buffer.from(JSON.stringify({title:'Valid',text:'water'})));
const damaged=Buffer.from(valid);damaged[damaged.length-1]^=1;
for(const compressed of [valid.subarray(0,-2),damaged,Buffer.concat([valid,Buffer.from([0])])]){
 const index=openFixture(fixture({compressed}));await index.open();await assert.rejects(index.record(index.header.docs_offset,0),/compressed document/);
}
const exact={title:'Water',text:''};const overhead=Buffer.byteLength(JSON.stringify(exact));exact.text='x'.repeat(1048576-overhead);
const atLimit=openFixture(fixture({record:exact}));await atLimit.open();assert.equal((await atLimit.record(atLimit.header.docs_offset,0)).text.length,exact.text.length);
const oversized=openFixture(fixture({record:{...exact,text:exact.text+'x'}}));await oversized.open();
await assert.rejects(oversized.record(oversized.header.docs_offset,0),/1 MiB/);
const compressedOversized=openFixture(fixture({compressed:Buffer.alloc(1048577)}));await compressedOversized.open();
await assert.rejects(compressedOversized.record(compressedOversized.header.docs_offset,0),/incomplete or damaged/);
for(const compressed of [zlib.deflateSync(Buffer.from([255])),zlib.deflateSync(Buffer.from('{'))]){
 const invalid=openFixture(fixture({compressed}));await invalid.open();await assert.rejects(invalid.record(invalid.header.docs_offset,0));
}
""")

    def test_old_formats_missing_native_support_and_bad_record_references_fail(self):
        self.js(r"""
for(const options of [{magic:'OWLIDX2\n'},{header:{version:2}},{header:{document_encoding:'unknown'}},{header:{postings_encoding:'unknown'}}])
 await assert.rejects(openFixture(fixture(options)).open(),/Rebuild/);
const saved=globalThis.DecompressionStream;
try{globalThis.DecompressionStream=undefined;await assert.rejects(openFixture(fixture()).open(),/static indexes/);}
finally{globalThis.DecompressionStream=saved;}
const index=openFixture(fixture());await index.open();
for(const [table,id]of [[0,0],[index.header.docs_offset,-1],[index.header.docs_offset,3],[index.header.lexicon_offset,1]])
 await assert.rejects(index.record(table,id),/Invalid/);
""")


if __name__ == "__main__":
    unittest.main()
