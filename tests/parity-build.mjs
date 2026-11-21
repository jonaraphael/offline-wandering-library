import {mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
import {dirname, join} from 'node:path';
import {buildLibrary} from '../web/builder.mjs';
import {Directory} from './browser-drive-fixture.mjs';

globalThis.crypto ||= webcrypto;
const [spec, output] = process.argv.slice(2);
const {assets, navigation, search, sourceRoot} = JSON.parse(await readFile(spec, 'utf8'));
const routes = Object.fromEntries(assets.map(asset => [asset.id, ['https://fixture.test/asset/' + asset.id]]));
const fixture = new Map(assets.map(asset => ['https://fixture.test/asset/' + asset.id, asset.source_url.slice('repo://'.length)]));
const drive = new Directory();
const result = await buildLibrary(drive, {assets, routes, navigation, search, fetchFile: async url => {
  const path = fixture.get(url) || join(sourceRoot, url.slice(search.base.length));
  return new Response(await readFile(path));
}});
if (!result.state.finished) throw Error(JSON.stringify(result.searchWarnings));
async function publish(dir, parent) {
  for await (const child of dir.values()) {
    const path = join(parent, child.name);
    if (child.kind === 'directory') await publish(child, path);
    else {
      await mkdir(dirname(path), {recursive: true});
      await writeFile(path, Buffer.from(await (await child.getFile()).arrayBuffer()));
    }
  }
}
await publish(drive, output);
