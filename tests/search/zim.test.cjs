const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Zim, readBlob} = require('../../src/owl/templates/zim.js');
const drive = require('../../src/owl/templates/zim-drive.js');
const {displayGuides} = require('../../src/owl/templates/search.js');
const {makeZim} = require('./zim-fixture.cjs');

const read = (options) => new Zim(new Blob([makeZim(options)])).init();

test('reads the ZIM header, MIME types, path index and variable-length directory entries', async () => {
  const zim = await read({longPath: true});
  assert.equal(zim.major, 6);
  assert.equal(zim.entryCount, 9);
  assert.equal((await zim.get('a'.repeat(2200))).title, 'Long path');
  assert.equal((await zim.get('_assets/marker.svg')).mime, 'image/svg+xml');
  assert.equal(await zim.get('missing'), null);
});

test('looks up modern and legacy title tables and resolves main-page redirects', async () => {
  for (const options of [{compactTitle: true, noMain: true}, {legacy: true}]) {
    const zim = await read(options);
    const main = await zim.get('@main');
    assert.equal(main.path, 'Cardiopulmonary_resuscitation');
    assert.equal((await zim.get('absent', {title: 'Fixture CPR'})).path, main.path);
    assert.equal((await zim.get('Redirect')).path, main.path);
    if (options.legacy) {
      assert.equal((await zim.get('_assets/marker.svg', {ns: 'I'})).mime, 'image/svg+xml');
      assert.equal((await zim.get('_assets/style.css', {ns: '-'})).mime, 'text/css');
    }
  }
});

test('reads zstd and plain clusters across arbitrary split boundaries and reuses zstd bytes', async () => {
  for (const compression of [1, 5]) {
    const data = makeZim({compression});
    const parts = [data.subarray(0, 17), data.subarray(17, 700), data.subarray(700, -20), data.subarray(-20)];
    const zim = await new Zim(parts.map(part => new Blob([part]))).init();
    const entry = await zim.get('Second');
    const first = await zim.blob(entry);
    assert.match(await first.text(), /Second-page marker/);
    const bytes = zim.bytesRead;
    assert.equal(await (await zim.blob(entry)).text(), await first.text());
    if (compression === 5) assert.equal(zim.bytesRead, bytes);
  }
});

test('rejects truncated headers, unsupported clusters, corrupt offsets and redirect cycles', async () => {
  const bytes = makeZim();
  await assert.rejects(() => new Zim(new Blob([bytes.subarray(0, 50)])).init(), /Invalid ZIM/);
  await assert.rejects(() => new Zim(new Blob([bytes.subarray(0, -100)])).init(), /Invalid ZIM/);
  const unsupported = await read({compression: 4});
  await assert.rejects(async () => unsupported.blob(await unsupported.get('@main')), {code: 'unsupported'});
  const cyclic = await read({cycle: true});
  await assert.rejects(() => cyclic.get('@main'), /Invalid ZIM redirect/);
  const offset = Number(bytes.readBigUInt64LE(48));
  const cluster = Number(bytes.readBigUInt64LE(offset));
  bytes.writeUInt32LE(0xfffffffe, cluster + 1);
  const corrupt = await new Zim(new Blob([bytes])).init();
  await assert.rejects(async () => corrupt.blob(await corrupt.get('@main')), /Invalid ZIM/);
});

const row = {id: 'wiki', path: 'LIBRARY/ZIM/WIKI/medical.zimaa', files: [
  {path: 'LIBRARY/ZIM/WIKI/medical.zimaa', bytes: 3}, {path: 'LIBRARY/ZIM/WIKI/medical.zimab', bytes: 5},
]};
const generation = 'INDEX/ab12cd34ef56';
const files = (folder, prefix) => row.files.map(({path, bytes}) => ({
  webkitRelativePath: folder + '/' + path.slice(prefix.length), size: bytes,
}));
const markers = folder => ({webkitRelativePath: folder + '/home.js', size: 1});

test('validates the current reader generation when choosing the drive, LIBRARY or ZIM', async () => {
  const root = [...files('KINGSTON', ''), {webkitRelativePath: 'KINGSTON/START_HERE.html'},
    markers('KINGSTON/LIBRARY/' + generation)];
  const library = [...files('LIBRARY', 'LIBRARY/'), markers('LIBRARY/' + generation)];
  const fallback = files('ZIM', 'LIBRARY/ZIM/');
  const sidecar = {webkitRelativePath: 'ZIM/WIKI/._medical.zimaa', size: 3};
  const withSidecar = drive.fileSource([...fallback, sidecar], generation, [row]);
  assert.equal(withSidecar.get('LIBRARY/' + sidecar.webkitRelativePath), undefined);
  assert.throws(() => drive.fileSource([sidecar, fallback[1]], generation, [row]), {code: 'folder'});
  for (const files of [root, library, fallback]) {
    assert.deepEqual((await drive.openParts(drive.fileSource(files, generation, [row]), row, true))
      .map(file => file.size), [3, 5]);
  }
  assert.throws(() => drive.fileSource(root, 'INDEX/old', [row]), {code: 'folder'});
  assert.throws(() => drive.fileSource(root.filter(file => file !== root[2]), generation, [row]), {code: 'folder'});
  assert.throws(() => drive.fileSource(fallback.slice(0, 1), generation, [row]), {code: 'folder'});
  assert.throws(() => drive.fileSource(files('OTHER', 'LIBRARY/ZIM/'), generation, [row]), {code: 'folder'});
  root[1].size = 4;
  await assert.rejects(() => drive.openParts(drive.fileSource(root, generation, [row]), row, true), {code: 'folder'});
  await assert.rejects(() => drive.openParts(drive.fileSource(root, generation, [row]), row), {code: 'file'});
});

test('locates folder handles and reads the exact cases and sizes of split files', async () => {
  const files = new Map([['START_HERE.html', 1], ['LIBRARY/' + generation + '/home.js', 1],
    ...row.files.map(({path, bytes}) => [path, bytes])]);
  const fake = (name, prefix = '') => ({name, async getDirectoryHandle(next) { return fake(next, prefix + next + '/'); },
    async getFileHandle(next) {
      const path = prefix + next;
      if (!files.has(path)) throw new DOMException('Missing', 'NotFoundError');
      return {getFile: async () => ({name: path, size: files.get(path)})};
    }});
  for (const [name, prefix] of [['KINGSTON', ''], ['LIBRARY', 'LIBRARY/'], ['ZIM', 'LIBRARY/ZIM/']]) {
    const source = await drive.handleSource(fake(name, prefix), generation, [row]);
    assert.deepEqual((await drive.openParts(source, row)).map(file => file.name), row.files.map(({path}) => path));
    files.delete(row.files[1].path);
    await assert.rejects(() => drive.openParts(source, row), {code: 'disconnected'});
    if (name === 'ZIM') await assert.rejects(() => drive.handleSource(fake(name, prefix), generation, [row]), {code: 'folder'});
    files.set(row.files[1].path, row.files[1].bytes);
  }
});

test('uses a stable disconnected error for failed and incomplete browser file reads', async () => {
  for (const name of ['NotReadableError', 'NotFoundError', 'UnknownError']) {
    const cause = new DOMException('File read failed', name);
    await assert.rejects(() => readBlob({text: async () => { throw cause; }}, 'text'), {code: 'disconnected', cause});
  }
  await assert.rejects(() => readBlob({size: 2, arrayBuffer: async () => new ArrayBuffer(1)}, 'arrayBuffer'),
    {code: 'disconnected'});
});

test('uses the page location for picker copy and round-trips archive routes and anchors', () => {
  for (const [pathname, folder] of [['/Volumes/KINGSTON/START_HERE.html', 'KINGSTON'],
    ['/E:/START_HERE.html', 'the E: drive'], ['/media/u/KINGSTON/START_HERE.html', 'KINGSTON'],
    ['/C:/My%20Library/START_HERE.html', 'My Library']]) assert.equal(drive.folderName(pathname), folder);
  assert.equal(drive.pickerLabel('mac', true), 'Select');
  assert.equal(drive.pickerLabel('windows', true), 'Select Folder');
  assert.equal(drive.pickerLabel('linux', true), 'Open');
  assert.equal(drive.pickerLabel('mac', false, true), 'Open');
  assert.equal(drive.pickerLabel('windows', false, true), 'Select Folder');
  for (const platform of ['mac', 'windows', 'linux']) assert.equal(drive.pickerLabel(platform, false, false, true), 'Upload');
  assert.equal(drive.pickerLabel('mac', false), 'Upload');
  assert.equal(drive.pickerLabel('iphone', false), 'Open');
  const route = drive.readRoute('archive/1', 'folder/Article #a?', 'frägment', 'A title', 'A section');
  assert.deepEqual(drive.parseRoute(route), {id: 'archive/1', path: 'folder/Article #a?', fragment: 'frägment',
    title: 'A title', section: 'A section'});
});

test('only moves a same-task reviewed guide ahead of an archive when drive access is missing', () => {
  const groups = [[{record: {topic: 'cpr', href: 'wiki.zim'}}], [{record: {topic: 'other', href: 'other.pdf'}}],
    [{record: {topic: 'cpr', href: 'cpr.pdf'}}]];
  assert.deepEqual(displayGuides(groups, true), groups);
  assert.deepEqual(displayGuides(groups, false), [groups[2], groups[1], groups[0]]);
  assert.equal(groups[0][0].record.href, 'wiki.zim');
});
