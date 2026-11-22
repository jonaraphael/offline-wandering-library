"""Exercise the generated standalone Manage page and its selection handlers."""
import shutil
import subprocess
import unittest
from pathlib import Path
from owl.selector import make_model, render_selector

ROOT = Path(__file__).resolve().parents[1]
DOM = r"""
const fs=require('fs'), html=fs.readFileSync(0,'utf8'), nodes=new Map();
const assert=(value,message)=>{if(!value)throw Error(message);};
function node() {
  return {children:[],dataset:{},style:{setProperty(){}},attributes:{},handlers:{},value:'',hidden:false,disabled:false,
    classList:{toggle(){}},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
    setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,v){this.handlers[k]=v;},contains(){return false;},
    querySelectorAll(){return [];},focus(){}};
}
for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
  const item=node(); item.hidden=/\bhidden\b/.test(match[0]); item.value=(match[0].match(/\bvalue="([^"]*)"/)||[])[1]||''; nodes.set(match[1],item);
}
const get=id=>nodes.get(id), click=id=>get(id).handlers.click({preventDefault(){}});
get('owl-model').textContent=html.match(/<script id="owl-model"[^>]*>([\s\S]*?)<\/script>/)[1];
if(get('shell'))get('shell').value='posix';
const body=node();
globalThis.document={body,activeElement:body,getElementById:get,createElement:node,querySelector:node};
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g))eval(script[1]);
"""
NODE = shutil.which("node")


def run_script(html, script):
    return subprocess.run([NODE, "-e", DOM + script], input=html, text=True, capture_output=True, timeout=60)


@unittest.skipUnless(NODE, "Node required for selector UI checks")
class SelectorInteractionTests(unittest.TestCase):
    def test_opening_source_template_links_to_generated_selector(self):
        result = run_script((ROOT / "src/owl/templates/selector.html").read_text(), r"""
const notice=get('fatal');
assert(!notice.hidden&&notice.children[1].href==='../../../SELECT.html','Generated planner link missing');
assert(!globalThis.OWLPlanner,'The unbuilt engine ran');
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manage_search_files_editions_reset_and_cli(self):
        model = make_model(ROOT / "catalog/library.yaml", ROOT / "profiles", ROOT / "catalog/resources.yaml")
        result = run_script(render_selector(model), r"""
const categories=get('categories').children;
const cards=categories.flatMap(category=>category.children.slice(1));
const card=id=>cards.find(row=>row.dataset.resourceId===id);
const search=value=>get('collection-search').handlers.input({target:{value}});
assert(!get('manage').hidden&&get('manage-done').hidden,'Standalone Manage did not open');
assert(categories.length===8,'Expected eight categories');
assert(get('preview-sizes').children.find(chip=>chip.dataset.size===64).attributes['aria-pressed']==='true','Default size is 64 GB');
assert(get('plan-command').value.includes('--capacity-bytes 64000000000'),'Command does not use preview size');
assert(get('reset-recommended').hidden,'Reset visible on fresh preview');
search('seed-processing-quality');
click('exclude-filtered');
search('seed drying');
const seeds=card('seed-processing-quality');
assert(!seeds.hidden&&cards.filter(row=>!row.hidden).length===1,'File alias did not find the collection');
assert(categories.find(category=>category.children.includes(seeds)).open,'Search did not open the category');
click('exclude-filtered');
click('include-filtered');
assert(get('plan-command').value.includes('seed-processing-quality=fao_seed_processing'),'Bulk choice did not use the matched file');

search('');
const details=seeds.children[1];
details.children.find(node=>node.textContent==='Choose files').handlers.click({preventDefault(){}});
const fileList=details.children.find(node=>node.className==='file-list');
assert(!fileList.hidden&&fileList.children.length===2,'Choose files did not open both files');
const quality=fileList.children.flatMap(li=>li.children.flatMap(label=>label.children)).find(input=>input.dataset.file==='fao_seed_quality');
quality.checked=true;
quality.handlers.change();
assert(get('plan-command').value.includes('fao_seed_quality')||!get('plan-command').value.includes('--resource-assets seed-processing-quality='),'File checkbox did not include the selected file');
const wikipedia=card('wikipedia-en');
const editions=wikipedia.children[1].children.find(node=>node.className==='editions');
assert(editions.children.some(option=>option.textContent.endsWith('(recommended)')),'Recommended edition missing');
editions.children.find(option=>option.dataset.edition==='nopic').handlers.click();
assert(get('plan-command').value.includes('--edition wikipedia-en=nopic'),'Edition absent from command');
assert(!get('reset-recommended').hidden,'Reset unavailable after changing editions');
click('reset-recommended');
assert(get('reset-recommended').hidden,'Default library was not restored');
search('nothing-matches-here-xyz');
assert(get('include-filtered').disabled&&!get('no-collections').hidden,'No results feedback is missing');
""")
        self.assertEqual(result.returncode, 0, result.stderr)
