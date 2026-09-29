/* Exercise the actual metadata matcher without a browser or network. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
const api = require(spec.runtime);
let payload;
vm.runInNewContext(fs.readFileSync(path.join(spec.library, spec.manifest.path), 'utf8'), {
  OWLDiscoveryData: value => { payload = value; }
});
const prepared = api.prepare(payload.records);
for (const sample of spec.samples) {
  const hits = api.search(prepared, sample.title, 'all-with-legacy');
  if (!hits.some(hit => hit.record.id === sample.id)) throw Error('Title not discoverable: ' + sample.id);
}
console.log(JSON.stringify({status:'passed', records:prepared.length, queries:spec.samples.length}));
